"""Padrón político único: Gobierno por defecto, Privada donde Gobierno no tiene dato (ADR-027,
docs/files/spec-padron-politico-gobierno-privada.md §2 y §4).

- `combinar`: el valor de cada campo con su origen, por localidad del nomenclador.
- `cruzar`: Gobierno contra el valor original de Privada (su respaldo), para el panel.

Privada se vincula por `id_geo` (las dos bases usan el padrón oficial, ADR-026). Varias filas de
Privada pueden compartir un `id_geo`: se toma la primera con dato.
"""
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gob_politico.models import ExtGobIntendente, ExtPrivPadronPolitico
from app.gob_politico.parse import clave_nombre
from app.gobierno.models import ExtGobLocalidad

GOBIERNO = "gobierno"
PRIVADA = "privada"
CAMPOS = ("intendente", "partido")
# Estados del cruce, en el orden en que se muestran.
ESTADOS = ("igual", "igual_otro_orden", "parecido", "distinto", "solo_gobierno", "solo_privada", "sin_dato")


@dataclass
class ValorPrivada:
    intendente: str | None = None
    partido: str | None = None
    intendente_respaldo: str | None = None
    partido_respaldo: str | None = None


def _palabras(s: str) -> frozenset[str]:
    return frozenset(clave_nombre(s.replace(",", " ")).split())


def comparar(gobierno: str | None, privada: str | None) -> str:
    if not gobierno and not privada:
        return "sin_dato"
    if not privada:
        return "solo_gobierno"
    if not gobierno:
        return "solo_privada"
    if clave_nombre(gobierno) == clave_nombre(privada):
        return "igual"
    g, p = _palabras(gobierno), _palabras(privada)
    if g == p:
        return "igual_otro_orden"
    return "parecido" if g & p else "distinto"


def privada_por_id_geo(filas: list[ExtPrivPadronPolitico]) -> dict[str, ValorPrivada]:
    out: dict[str, ValorPrivada] = {}
    for f in filas:
        if not f.id_geo:
            continue
        v = out.setdefault(f.id_geo, ValorPrivada())
        for campo in CAMPOS:
            for sufijo in ("", "_respaldo"):
                if getattr(v, campo + sufijo) is None and getattr(f, campo + sufijo):
                    setattr(v, campo + sufijo, getattr(f, campo + sufijo))
    return out


def combinar(
    universo: list[ExtGobLocalidad], gobierno: dict[str, ExtGobIntendente], privada: dict[str, ValorPrivada]
) -> list[dict]:
    out = []
    for loc in universo:
        g = gobierno.get(loc.codigo_indec)
        p = privada.get(loc.id_geo or "")
        fila = {"codigo_indec": loc.codigo_indec, "id_geo": loc.id_geo, "localidad": loc.nombre_gob, "departamento": loc.departamento_gob}
        for campo in CAMPOS:
            vg = getattr(g, campo) if g else None
            vp = getattr(p, campo) if p else None
            fila[campo] = vg or vp
            fila[f"origen_{campo}"] = GOBIERNO if vg else PRIVADA if vp else None
        out.append(fila)
    return out


def cruzar(
    universo: list[ExtGobLocalidad], gobierno: dict[str, ExtGobIntendente], privada: dict[str, ValorPrivada]
) -> tuple[dict[str, dict[str, int]], list[dict]]:
    """Conteo por campo y estado, y las localidades que no son iguales. Compara contra el
    respaldo de Privada (su valor original)."""
    conteo: dict[str, Counter] = {c: Counter() for c in CAMPOS}
    filas = []
    for loc in universo:
        g = gobierno.get(loc.codigo_indec)
        p = privada.get(loc.id_geo or "")
        for campo in CAMPOS:
            vg = getattr(g, campo) if g else None
            vp = getattr(p, f"{campo}_respaldo") if p else None
            estado = comparar(vg, vp)
            conteo[campo][estado] += 1
            if estado not in ("igual", "igual_otro_orden", "sin_dato"):
                filas.append({
                    "localidad": loc.nombre_gob, "departamento": loc.departamento_gob, "campo": campo,
                    "estado": estado, "gobierno": vg, "privada": vp,
                })
    resumen = {c: {e: conteo[c][e] for e in ESTADOS if conteo[c][e]} for c in CAMPOS}
    return resumen, sorted(filas, key=lambda f: (ESTADOS.index(f["estado"]), f["departamento"], f["localidad"], f["campo"]))


async def leer(db: AsyncSession) -> tuple[list[ExtGobLocalidad], dict[str, ExtGobIntendente], dict[str, ValorPrivada]]:
    universo = list(
        (await db.execute(select(ExtGobLocalidad).where(ExtGobLocalidad.deleted_at.is_(None)).order_by(ExtGobLocalidad.codigo_indec))).scalars()
    )
    gobierno = {i.codigo_indec: i for i in (await db.execute(select(ExtGobIntendente))).scalars()}
    privada = privada_por_id_geo(list((await db.execute(select(ExtPrivPadronPolitico))).scalars()))
    return universo, gobierno, privada


async def padron_combinado(db: AsyncSession) -> list[dict]:
    """Para `GET /internal/datos-externos/padron-politico`: solo localidades con `id_geo`."""
    return [f for f in combinar(*await leer(db)) if f["id_geo"]]
