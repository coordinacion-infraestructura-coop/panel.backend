"""Carga de las planillas de CC y CH en la planificación de programas (ADR-036,
docs/files/spec-privada-planificacion-programas.md §9 Fase 5 y §13).

Idempotente y re-ejecutable con una versión nueva de la planilla: crea el programa si no existe
(por nombre), da de alta las localidades que todavía no tienen fila y, en las que ya tienen,
actualiza cada campo con lo que dice la planilla — **salvo los campos que una persona editó en
la pantalla** (el último cambio de ese campo en el historial no es de `carga-inicial`): esos no
se tocan y se listan en el informe. Valida con las mismas reglas del servicio y deja cada cambio
en el historial con el usuario `carga-inicial`.

Uso (desde services/svc-privada, con DATABASE_URL apuntando a la base):
    python -m scripts.seed_planificacion.cargar            # simulacro: hace todo y hace ROLLBACK
    python -m scripts.seed_planificacion.cargar --aplicar  # COMMIT
    (--detalle agrega al informe, campo por campo, lo que cambia en cada fila existente)

Los CSV se regeneran con `emparejar_cordon_cuneta.py` / `emparejar_cordoba_hogar.py` (ver README).

Decisiones de mapeo (usuario, 2026-11-19; CC revisado con la planilla del 2026-11-20):
- Prioridad = color de la fila, en la escala del panel (celeste 1, verde 2, naranja 3, amarillo 4,
  rojo 5, gris X = desestimado). En CC manda el color, no el número: la versión del 2026-11-20
  numera 1–6 con la lavanda en el 2, y la anterior tenía números de una escala vieja o vacíos.
- CC lavanda → estado "Resuelto por ATP", sin prioridad (la fila no tiene otro color).
  CC rosa ("corrección nota de pedido") → sin prioridad.
- CH violeta/lavanda → estado "Resuelto por ATP" + la prioridad del color de abajo.
- "MONTO FIRMADO O SUGERIDO" → Monto sugerido; "MONTO" numérico → Monto firmado. Ambas
  columnas están en millones cuando el valor es < 100.000 ("150M" = 150 millones).
- Textos sueltos de la planilla (MONTO no numérico, columnas finales sin título con saldos de
  ATP) → se agregan a la Observación, para no perderlos.
- CH: columna "Cantidad de viviendas" (número), vacía en la planilla, se crea igual.
- Santiago Temple: id_geo del espejo `priv_geo_localidades`.
- Pedro E. Vivas (Km. 658) en CH: misma vinculación que en CC (195); el posible duplicado con
  Kilómetro 658 lo revisa el usuario a mano.
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
ATP = "Resuelto por ATP"
DETALLE = "--detalle" in sys.argv  # lista campo por campo lo que cambia en cada fila existente


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
        if v and not re.fullmatch(r"[1-6]", v):  # los números sueltos de CC repiten el grupo
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
        sugerido_txt = r["monto_firmado_o_sugerido"].strip()
        if sugerido_txt and _monto(sugerido_txt) is None:
            notas.insert(0, f"Monto firmado o sugerido (planilla): {sugerido_txt}")
        if r["monto_nota"] and "convertido" not in r["monto_nota"]:
            notas.append(r["monto_nota"])
        res.append({
            "fila": r["fila_origen"], "id_geo": r["id_geo"], "localidad": r["localidad_planilla"],
            "departamento": r["departamento_planilla"], "metodo": r["metodo"],
            "prioridad": COLOR_A_PRIORIDAD.get(r["prioridad_color"]),
            "estado": ATP if r["prioridad_color"] == "lavanda" else None,
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
        if "VIVAS" in r["localidad_planilla"].upper():  # Pedro E. Vivas: misma vinculación que en CC (195)
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
    temple = (await db.execute(select(GeoLocalidad.id_geo).where(
        func.upper(GeoLocalidad.localidad) == "SANTIAGO TEMPLE", GeoLocalidad.activo.is_(True)))).scalars().all()

    columnas = {c.clave: c for c in (await db.execute(
        select(PlanColumna).where(PlanColumna.programa_id == pid, PlanColumna.deleted_at.is_(None)))).scalars()}
    activos = set((await db.execute(select(GeoLocalidad.id_geo).where(GeoLocalidad.activo.is_(True)))).scalars())
    nombre_prio = {p.id: p.nombre for p in (await db.execute(select(PlanPrioridad).where(PlanPrioridad.programa_id == pid))).scalars()}
    nombre_est = {e.id: e.nombre for e in (await db.execute(select(PlanEstado).where(PlanEstado.programa_id == pid))).scalars()}

    existentes = {pl.id_geo: pl for pl in (await db.execute(select(PlanLocalidad).where(
        PlanLocalidad.programa_id == pid, PlanLocalidad.deleted_at.is_(None)))).scalars()}
    # último autor de cada (id_geo, campo): si no es la carga, ese campo lo editó una persona
    ultimo: dict[tuple[str, str], str] = {}
    for h in (await db.execute(select(PlanHistorial).where(PlanHistorial.programa_id == pid)
                               .order_by(PlanHistorial.fecha, PlanHistorial.id))).scalars():
        ultimo[(h.id_geo, h.campo)] = h.usuario

    # Carga masiva (no fila por fila por la capa de servicio: ~10 consultas por fila a través del
    # proxy eran más de media hora). Mismas validaciones (`service._validar_valor`, catálogo del
    # programa, padrón activo) y mismo historial legible, en un solo flush.
    ahora = now_utc()
    cargadas = actualizadas = sin_cambios = salteadas = 0
    protegidos: list[str] = []
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
        if id_geo in vistos:
            informe.append(f"{nombre}: fila {f['fila']} {f['localidad']} — id_geo {id_geo} repetido en la planilla, se carga la primera")
            continue
        vistos.add(id_geo)
        valores: dict = {}
        try:
            for clave, v in f["valores"].items():
                limpio = service._validar_valor(columnas[clave], v) if v is not None else None
                if limpio is not None:
                    valores[clave] = limpio
        except Exception as exc:  # noqa: BLE001
            informe.append(f"{nombre}: fila {f['fila']} {f['localidad']} — valor inválido: {getattr(exc, 'detail', exc)}")
            salteadas += 1
            continue
        prioridad_id = estado_id = None
        if f["prioridad"]:
            prioridad_id = prios.get(f["prioridad"])
            if prioridad_id is None:
                informe.append(f"{nombre}: fila {f['fila']} prioridad {f['prioridad']} desconocida")
        if f["estado"]:
            estado_id = estados[f["estado"].lower()]

        pl = existentes.get(id_geo)
        hist: list[tuple[str, str | None, str | None]] = []
        if pl is None:
            if estado_id:
                hist.append(("estado", None, nombre_est[estado_id]))
            if prioridad_id:
                hist.append(("prioridad", None, nombre_prio[prioridad_id]))
            hist += [(k, None, service._legible(v)) for k, v in valores.items()]
            if not hist:
                salteadas += 1
                continue
            db.add(PlanLocalidad(
                programa_id=pid, id_geo=id_geo, prioridad_id=prioridad_id, estado_id=estado_id, valores=valores,
                created_at=ahora, created_by=ACTOR.email, updated_at=ahora, updated_by=ACTOR.email,
            ))
            cargadas += 1
        else:
            def editado(campo: str) -> bool:
                autor = ultimo.get((id_geo, campo))
                return autor is not None and autor != ACTOR.email

            for campo, attr, nuevo_id, nombres in (("estado", "estado_id", estado_id, nombre_est),
                                                    ("prioridad", "prioridad_id", prioridad_id, nombre_prio)):
                actual = getattr(pl, attr)
                if actual == nuevo_id:
                    continue
                if editado(campo):
                    protegidos.append(f"{nombre}: {f['localidad']} ({id_geo}) — {campo}: queda "
                                      f"{nombres.get(actual)!r} (editado en la pantalla); la planilla dice "
                                      f"{nombres.get(nuevo_id)!r}")
                    continue
                setattr(pl, attr, nuevo_id)
                hist.append((campo, nombres.get(actual), nombres.get(nuevo_id)))
            nuevos_valores = dict(pl.valores or {})
            for clave in f["valores"]:
                antes, despues = nuevos_valores.get(clave), valores.get(clave)
                if antes == despues:
                    continue
                if editado(clave):
                    protegidos.append(f"{nombre}: {f['localidad']} ({id_geo}) — {clave}: queda "
                                      f"{service._legible(antes)!r} (editado en la pantalla); la planilla dice "
                                      f"{service._legible(despues)!r}")
                    continue
                if despues is None:
                    nuevos_valores.pop(clave, None)
                else:
                    nuevos_valores[clave] = despues
                hist.append((clave, service._legible(antes), service._legible(despues)))
            if not hist:
                sin_cambios += 1
                continue
            pl.valores = nuevos_valores  # reasignar: JSON no detecta mutaciones in-place
            pl.updated_at, pl.updated_by = ahora, ACTOR.email
            actualizadas += 1
            if DETALLE:
                informe.append(f"  {nombre}: {f['localidad']} ({id_geo}) — " + "; ".join(
                    f"{c}: {a!r} → {n!r}" for c, a, n in hist))
        for campo, antes, nuevo in hist:
            db.add(PlanHistorial(programa_id=pid, id_geo=id_geo, campo=campo, valor_anterior=antes,
                                 valor_nuevo=nuevo, usuario=ACTOR.email, fecha=ahora))
    await db.flush()
    await audit.log_audit(db, actor=ACTOR, action="UPDATE", resource_type="privada_plan_carga_inicial",
                          resource_id=str(pid), payload={"programa": nombre, "altas": cargadas,
                                                         "actualizadas": actualizadas,
                                                         "fuente": f"planilla del área ({fuente})"})
    informe.insert(0, f"{nombre} (programa {pid}): {cargadas} altas, {actualizadas} actualizadas, "
                      f"{sin_cambios} sin cambios, {salteadas} salteadas, {len(protegidos)} campos editados "
                      f"en la pantalla que no se tocaron")
    informe.extend(protegidos)


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
