"""Carga inicial de las planillas de CC y CH en la planificación de programas (ADR-036,
docs/files/spec-privada-planificacion-programas.md §9 Fase 5 y §13).

Idempotente: crea el programa si no existe (por nombre) y sólo carga las localidades que todavía
no tienen fila en ese programa — nunca pisa lo que alguien ya editó en la pantalla. Valida con
las mismas reglas del servicio y deja cada valor en el historial con el usuario `carga-inicial`.

Uso (desde services/svc-privada, con DATABASE_URL apuntando a la base):
    python -m scripts.seed_planificacion.cargar            # simulacro: hace todo y hace ROLLBACK
    python -m scripts.seed_planificacion.cargar --aplicar  # COMMIT

Decisiones de mapeo (usuario, 2026-11-19):
- Prioridad: CC = columna sin título (1–5/X); CH = color de fila (misma escala, gris = X).
- CH violeta/lavanda → estado "Resuelto por ATP" + la prioridad del color de abajo.
- "MONTO FIRMADO O SUGERIDO" → Monto sugerido; "MONTO" numérico → Monto firmado. Ambas
  columnas están en millones cuando el valor es < 100.000 ("150M" = 150 millones).
- Textos sueltos de la planilla (MONTO no numérico, columnas finales sin título con saldos de
  ATP) → se agregan a la Observación, para no perderlos.
- CH: columna "Cantidad de viviendas" (número), vacía en la planilla, se crea igual.
- Santiago Temple: id_geo del espejo `priv_geo_localidades`.
"""
import asyncio
import csv
import re
import sys
from pathlib import Path

from sqlalchemy import func, select

from app import audit
from app.auth import AuthUser
from app.common import now_utc
from app.database import AsyncSessionLocal
from app.planificacion import service
from app.planificacion.models import (
    PlanColumna, PlanEstado, PlanHistorial, PlanLocalidad, PlanPrioridad, PlanPrograma,
)
from app.territorial.models import GeoLocalidad

DIR = Path(__file__).parent
ACTOR = AuthUser(uid="carga-inicial", email="carga-inicial", role="Admin", secretarias=["privada"])
COLOR_A_PRIORIDAD = {"celeste": "1", "verde": "2", "naranja": "3", "amarillo": "4", "rojo": "5", "gris": "X"}


def _monto(txt: str) -> float | None:
    t = (txt or "").strip().upper().replace("$", "").replace(" ", "")
    if not t:
        return None
    m = re.fullmatch(r"([\d.,]+)M?", t)
    if not m:
        return None
    n = float(m.group(1).replace(".", "").replace(",", "."))
    return n * 1_000_000 if (t.endswith("M") or n < 100_000) else n


def _texto_suelto(*valores: str) -> list[str]:
    out = []
    for v in valores:
        v = (v or "").strip()
        if v and not re.fullmatch(r"[1-5]", v):  # los 1–5 sueltos de CC repiten el grupo
            out.append(v)
    return out


def filas_cc() -> list[dict]:
    res = []
    for r in csv.DictReader(open(DIR / "cordon_cuneta_general.csv", encoding="utf-8-sig")):
        monto_txt = r["monto"].strip()
        firmado = _monto(monto_txt)
        notas = _texto_suelto(r["col_extra"], r["col_extra_2"])
        if monto_txt and firmado is None:
            notas.insert(0, f"Monto (planilla): {monto_txt}")
        if r["monto_nota"] and "convertido" not in r["monto_nota"]:
            notas.append(r["monto_nota"])
        res.append({
            "fila": r["fila_origen"], "id_geo": r["id_geo"], "localidad": r["localidad_planilla"],
            "departamento": r["departamento_planilla"], "metodo": r["metodo"],
            "prioridad": (r["prioridad"] or "").strip().upper() or None,
            "estado": None,
            "valores": {
                "anuncio_gobernador": {"SI": True, "NO": False}.get(r["anuncio_gobernador"].strip().upper()),
                "monto_sugerido": _monto(r["monto_firmado_o_sugerido"]),
                "monto_firmado": firmado,
                "observacion": " · ".join([x for x in [r["observacion"].strip()] + notas if x]) or None,
            },
        })
    return res


def filas_ch() -> list[dict]:
    res = []
    for r in csv.DictReader(open(DIR / "cordoba_hogar_general.csv", encoding="utf-8-sig")):
        id_geo, metodo = r["id_geo"], r["metodo"]
        if r["fila_origen"] == "244":  # Pedro E. Vivas: misma vinculación que en CC (195)
            id_geo, metodo = "195", "igual_que_cc"
        res.append({
            "fila": r["fila_origen"], "id_geo": id_geo, "localidad": r["localidad_planilla"],
            "departamento": r["departamento_planilla"], "metodo": metodo,
            "prioridad": r["prioridad_propuesta"] if r["prioridad_propuesta"] not in ("", "?") else None,
            "estado": r["estado_propuesto"] or None,
            "valores": {
                "anuncio_gobernador": {"SI": True, "NO": False}.get(r["anuncio_gobernador"].strip().upper()),
                "observacion": r["observacion"].strip() or None,
                "cantidad_de_viviendas": float(r["cantidad_viviendas"]) if r["cantidad_viviendas"].strip() else None,
            },
        })
    return res


async def _programa(db, nombre: str, fuente: str) -> int:
    pid = (
        await db.execute(
            select(PlanPrograma.id).where(func.lower(PlanPrograma.nombre) == nombre.lower(), PlanPrograma.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if pid:
        return pid
    p = await service.crear_programa(db, ACTOR, {"nombre": nombre, "area": "vivienda", "fuente": fuente,
                                                 "descripcion": "Carga inicial desde la planilla del área (2026-11-19)",
                                                 "orden": 1 if fuente == "cordon_cuneta" else 2, "activo": True})
    return p["id"]


async def _cargar(db, nombre: str, fuente: str, filas: list[dict], informe: list[str]) -> None:
    pid = await _programa(db, nombre, fuente)
    if fuente == "cordoba_hogar":
        claves = set((await db.execute(select(PlanColumna.clave).where(PlanColumna.programa_id == pid))).scalars())
        if "cantidad_de_viviendas" not in claves:
            await service.crear_item(db, ACTOR, pid, "columnas", {"nombre": "Cantidad de viviendas", "tipo": "numero", "orden": 5, "visible": True})
    prios = {p.codigo.upper(): p.id for p in (await db.execute(
        select(PlanPrioridad).where(PlanPrioridad.programa_id == pid, PlanPrioridad.deleted_at.is_(None)))).scalars()}
    estados = {e.nombre.lower(): e.id for e in (await db.execute(
        select(PlanEstado).where(PlanEstado.programa_id == pid, PlanEstado.deleted_at.is_(None)))).scalars()}
    ya = set((await db.execute(select(PlanLocalidad.id_geo).where(PlanLocalidad.programa_id == pid, PlanLocalidad.deleted_at.is_(None)))).scalars())
    temple = (await db.execute(select(GeoLocalidad.id_geo).where(
        func.upper(GeoLocalidad.localidad) == "SANTIAGO TEMPLE", GeoLocalidad.activo.is_(True)))).scalars().all()

    columnas = {c.clave: c for c in (await db.execute(
        select(PlanColumna).where(PlanColumna.programa_id == pid, PlanColumna.deleted_at.is_(None)))).scalars()}
    activos = set((await db.execute(select(GeoLocalidad.id_geo).where(GeoLocalidad.activo.is_(True)))).scalars())
    nombre_prio = {p.id: p.nombre for p in (await db.execute(select(PlanPrioridad).where(PlanPrioridad.programa_id == pid))).scalars()}
    nombre_est = {v: k for k, v in estados.items()}

    # Carga masiva (no fila por fila por la capa de servicio: ~10 consultas por fila a través del
    # proxy eran más de media hora). Mismas validaciones (`service._validar_valor`, catálogo del
    # programa, padrón activo) y mismo historial legible, en un solo flush.
    ahora = now_utc()
    cargadas = salteadas = 0
    vistos: set[str] = set()
    for f in filas:
        id_geo = f["id_geo"]
        if not id_geo and f["localidad"].strip().upper() == "SANTIAGO TEMPLE" and len(temple) == 1:
            id_geo = temple[0]
        if not id_geo:
            informe.append(f"{nombre}: fila {f['fila']} {f['localidad']} — sin id_geo ({f['metodo']}), no se carga")
            salteadas += 1
            continue
        if id_geo not in activos:
            informe.append(f"{nombre}: fila {f['fila']} {f['localidad']} — id_geo {id_geo} no está activo en el padrón")
            salteadas += 1
            continue
        if id_geo in ya:
            salteadas += 1
            continue
        if id_geo in vistos:
            informe.append(f"{nombre}: fila {f['fila']} {f['localidad']} — id_geo {id_geo} repetido en la planilla, se carga la primera")
            continue
        vistos.add(id_geo)
        valores: dict = {}
        hist: list[tuple[str, str | None]] = []
        try:
            for clave, v in f["valores"].items():
                if v is None:
                    continue
                limpio = service._validar_valor(columnas[clave], v)
                if limpio is not None:
                    valores[clave] = limpio
                    hist.append((clave, service._legible(limpio)))
        except Exception as exc:  # noqa: BLE001
            informe.append(f"{nombre}: fila {f['fila']} {f['localidad']} — valor inválido: {getattr(exc, 'detail', exc)}")
            salteadas += 1
            continue
        prioridad_id = estado_id = None
        if f["prioridad"]:
            prioridad_id = prios.get(f["prioridad"])
            if prioridad_id is None:
                informe.append(f"{nombre}: fila {f['fila']} prioridad {f['prioridad']} desconocida")
            else:
                hist.insert(0, ("prioridad", nombre_prio[prioridad_id]))
        if f["estado"]:
            estado_id = estados[f["estado"].lower()]
            hist.insert(0, ("estado", nombre_est[estado_id]))
        if not hist:
            salteadas += 1
            continue
        db.add(PlanLocalidad(
            programa_id=pid, id_geo=id_geo, prioridad_id=prioridad_id, estado_id=estado_id, valores=valores,
            created_at=ahora, created_by=ACTOR.email, updated_at=ahora, updated_by=ACTOR.email,
        ))
        for campo, nuevo in hist:
            db.add(PlanHistorial(programa_id=pid, id_geo=id_geo, campo=campo, valor_anterior=None,
                                 valor_nuevo=nuevo, usuario=ACTOR.email, fecha=ahora))
        cargadas += 1
    await db.flush()
    await audit.log_audit(db, actor=ACTOR, action="CREATE", resource_type="privada_plan_carga_inicial",
                          resource_id=str(pid), payload={"programa": nombre, "localidades": cargadas,
                                                         "fuente": "planilla del área, 2026-11-19"})
    informe.insert(0, f"{nombre} (programa {pid}): {cargadas} localidades cargadas, {salteadas} salteadas")


async def main(aplicar: bool) -> None:
    informe: list[str] = []
    async with AsyncSessionLocal() as db:
        await _cargar(db, "Cordón Cuneta", "cordon_cuneta", filas_cc(), informe)
        await _cargar(db, "Córdoba Hogar", "cordoba_hogar", filas_ch(), informe)
        if aplicar:
            await db.commit()
        else:
            await db.rollback()
    print(("APLICADO" if aplicar else "SIMULACRO (rollback)") + "\n" + "\n".join(informe))


if __name__ == "__main__":
    asyncio.run(main("--aplicar" in sys.argv))
