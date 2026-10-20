"""Sync de fuentes oficiales públicas (spec-datos-externos-fuentes-oficiales.md §4).

Cuatro fuentes independientes, en este orden: `estadistica` (trae los
polígonos que usan las otras), `renabap`, `idecor_equipamientos` e
`idecor_vitales`. Cada una corre en su SAVEPOINT, reemplaza el contenido de sus
tablas y deja una fila en `ext_fuentes_oficiales_sync_log`; si falla, no toca
lo que había y las demás siguen.
"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.fuentes_oficiales import clientes
from app.fuentes_oficiales.clientes import FuenteFallida
from app.fuentes_oficiales.geo import IndicePoligonos, centroide
from app.fuentes_oficiales.models import (
    ExtEquipamiento,
    ExtEstadisticaVital,
    ExtEstDepartamento,
    ExtEstGobiernoLocal,
    ExtEstPoligono,
    ExtFuentesOficialesSyncLog,
    ExtRenabapBarrio,
)
from app.gobierno.models import ExtGobLocalidad
from app.gobierno.sync import normalizar_codigo
from app.transferencias.extract import normalize_name

logger = logging.getLogger(__name__)

FUENTES = ("estadistica", "renabap", "idecor_equipamientos", "idecor_vitales")

_CODIGO_PROVINCIA = {"14", "14000"}
_MAX_ANOMALIAS = 200

# ── Estadística: columna destino → campo de la capa ──────────────────────────
# El campo de código de cada capa va aparte. Si falta cualquiera de estos
# campos en la respuesta, la fuente cambió de esquema y falla entera.

_FICHA = {
    "nombre": "gobierno_local",
    "tipo_2022": "situación_al_año_2022",
    "poblacion_2010": "total_de_población_2010",
    "poblacion_2022": "total_de_población_2022",
    "variacion_intercensal": "variación_intercensal",
    "superficie_km2": "superficie_en_km2",
    "densidad": "densidad_poblacional",
    "hogares": "hogares",
    "personas_por_hogar": "promedio_de_personas_por_hogar",
    "pct_0_17": "niñas_os_y_adolescentes_de_0_a",
    "pct_65_mas": "adultos_mayores__65_y_más____",
    "coef_vejez": "coeficiente_de_vejez_demográfic",
}
_CONDVIDA = {
    "nbi_pct": "porcentaje_de_hogares_con_al_me",
    "nbi_vivienda_pct": "tipología_de_nbi___vivienda____",
    "nbi_sanitaria_pct": "tipología_de_nbi___condiciones",
    "nbi_hacinamiento_pct": "tipología_de_nbi___hacinamiento",
    "nbi_escolar_pct": "tipología_de_nbi__asistencia_es",
    "nbi_subsistencia_pct": "tipología_de_nbi__capacidad_de",
    "agua_red_pct": "tenencia_de_servicios___red_púb",
    "cloacas_pct": "tenencia_de_servicios__cloacas",
    "gas_red_pct": "tenencia_de_servicios___gas_de",
    "internet_pct": "tenencia_de_servicios___tenenci",
    "propietarios_pct": "regimen_de_tenencia___propietar",
    "inquilinos_pct": "regimen_de_tenencia___inquilino",
    "otra_tenencia_pct": "regimen_de_tenencia___otro",
    "calidad_i_pct": "calidad_de_los_materiales___c_1",
    "calidad_ii_pct": "calidad_de_los_materiales___c_2",
    "calidad_iii_pct": "calidad_de_los_materiales___c_3",
    "calidad_iv_pct": "calidad_de_los_materiales___c_4",
}
_POBVIV = {
    "hogares_total": "total_hogares",
    "hogares_hacinamiento": "hacinamiento",
    "hogares_sanitaria": "condiciones_sanitarias",
    "hogares_vivienda_inconveniente": "vivienda_de_tipo_inconveniente",
    "hogares_calidad_iii": "calidad_iii",
    "hogares_calidad_iv": "calidad_iv",
    "hogares_lena_carbon": "leña_o_carbón",
    "hogares_alquilan": "alquilada",
}
_EDUCACION = {
    "asistencia_10_18_pct": "asistencia_de_10_a_18____",
    "secundario_completo_pct": "secundario_completo_18_y_más___",
    "universitario_completo_pct": "universitario_completo28_y_más",
}
_SALUD = {"cobertura_salud_pct": "cobertura_de_salud___población"}
_LABORAL = {"desocupacion_pct": "tasa_de_desocupacion", "actividad_principal": "actividad_principal"}
_IPS = {
    "ips_valor": "índice_de_progreso_social_valor",
    "ips_nivel": "índice_de_progreso_social__nive",
    "ips_necesidades_basicas": "necesidades_humanas_básicas_val",
    "ips_fundamentos_bienestar": "fundamentos_del_bienestar__valo",
    "ips_oportunidades": "oportunidades__valor",
    "ips_variacion_interanual": "variacion_interanual_ips",
}

_ENTEROS = {"poblacion_2010", "poblacion_2022", "hogares", *_POBVIV}
_TEXTOS = {"nombre", "tipo_2022", "actividad_principal", "ips_nivel"}

# (setting con el nombre de la capa, campo de código, mapeo, nombre corto para `crudo`)
_CAPAS_GL = (
    ("est_capa_ficha", "código_gobierno_local", _FICHA, "ficha"),
    ("est_capa_condvida", "código_gobierno_local", _CONDVIDA, "condiciones_vida"),
    ("est_capa_pobviv", "codgl", _POBVIV, "hogares"),
    ("est_capa_educacion", "código_gobierno_local", _EDUCACION, "educacion"),
    ("est_capa_salud", "código_gobierno_local", _SALUD, "salud"),
    ("est_capa_laboral", "código_gobierno_local_2", _LABORAL, "empleo"),
    ("est_capa_ips", "id_2", _IPS, "ips"),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    f = _float(v)
    return int(round(f)) if f is not None else None


def _texto(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _convertir(columna: str, valor: Any) -> Any:
    if columna in _TEXTOS:
        return _texto(valor)
    if columna in _ENTEROS:
        return _int(valor)
    return _float(valor)


def _codigo(v: Any) -> str | None:
    """`normalizar_codigo` espera int/float o texto; los números llegan como
    `Decimal` (se parsean así para no perder centavos) y `"142007.0"` como texto
    se leería como `"1420070"`."""
    return normalizar_codigo(float(v) if isinstance(v, Decimal) else v)


def _dpto_indec(codigo_departamento: Any) -> str | None:
    """`154` → `"14154"` (código INDEC de departamento, como `link` de la capa
    de departamentos y `codigo_dpto_indec` del nomenclador)."""
    n = _int(codigo_departamento)
    return f"14{n:03d}" if n is not None else None


def _json_simple(v: Any) -> Any:
    return float(v) if isinstance(v, Decimal) else v


def _validar_campos(filas: list[dict], campos: list[str], capa: str) -> None:
    if not filas:
        raise FuenteFallida(f"{capa}: la capa vino vacía")
    faltan = [c for c in campos if c not in filas[0]]
    if faltan:
        raise FuenteFallida(f"{capa} cambió de esquema, faltan: {', '.join(faltan)}")


def _anomalia(anomalias: list[dict], **kw: Any) -> None:
    if len(anomalias) < _MAX_ANOMALIAS:
        anomalias.append(kw)


# ── Fuente: estadistica ───────────────────────────────────────────────────────

async def _sync_estadistica(db: AsyncSession, client: httpx.AsyncClient, anomalias: list[dict]) -> tuple[int, int]:
    filas_gl: dict[str, dict[str, Any]] = {}
    crudo: dict[str, dict[str, dict]] = defaultdict(dict)
    leidas = 0

    for setting, campo_codigo, mapeo, corto in _CAPAS_GL:
        capa = getattr(settings, setting)
        filas = await clientes.arcgis_query(client, capa)
        _validar_campos(filas, [campo_codigo, *mapeo.values()], capa)
        leidas += len(filas)
        vistos: set[str] = set()
        for f in filas:
            codigo = _codigo(f.get(campo_codigo))
            if codigo is None or codigo in _CODIGO_PROVINCIA:
                continue
            if codigo in vistos:
                _anomalia(anomalias, tipo="codigo_repetido", capa=corto, codigo=codigo)
                continue
            vistos.add(codigo)
            if corto != "ficha" and codigo not in filas_gl:
                _anomalia(anomalias, tipo="codigo_sin_ficha", capa=corto, codigo=codigo)
                continue
            destino = filas_gl.setdefault(codigo, {})
            if corto == "ficha":
                destino["codigo_dpto_indec"] = _dpto_indec(f.get("código_departamento"))
            for columna, campo in mapeo.items():
                destino[columna] = _convertir(columna, f.get(campo))
            crudo[codigo][corto] = {k: _json_simple(v) for k, v in f.items() if not k.startswith("Shape__") and k != "objectid"}

    if len(filas_gl) < 400:
        raise FuenteFallida(f"FichaGral trajo solo {len(filas_gl)} gobiernos locales (se esperan 427)")

    deptos = await clientes.arcgis_query(client, settings.est_capa_departamentos)
    _validar_campos(deptos, ["link", "nam_de", "pob_2022", "pob_2010", "sup_km2"], settings.est_capa_departamentos)
    poligonos = await clientes.arcgis_query(client, settings.est_capa_poligonos, geometria=True)
    _validar_campos(poligonos, ["cgl"], settings.est_capa_poligonos)

    ahora = _now()
    await db.execute(delete(ExtEstGobiernoLocal))
    for codigo, valores in filas_gl.items():
        db.add(ExtEstGobiernoLocal(codigo_indec=codigo, crudo=crudo[codigo], synced_at=ahora, **valores))

    suma_2010: dict[str, int] = defaultdict(int)
    suma_2022: dict[str, int] = defaultdict(int)
    for valores in filas_gl.values():
        dpto = valores.get("codigo_dpto_indec")
        if dpto:
            suma_2010[dpto] += valores.get("poblacion_2010") or 0
            suma_2022[dpto] += valores.get("poblacion_2022") or 0
    await db.execute(delete(ExtEstDepartamento))
    for d in deptos:
        codigo = _codigo(d.get("link"))
        if not codigo:
            continue
        p2010, p2022 = _int(d.get("pob_2010")), _int(d.get("pob_2022"))
        db.add(ExtEstDepartamento(
            codigo_dpto_indec=codigo,
            nombre=_texto(d.get("nam_de")),
            poblacion_2010=p2010,
            poblacion_2022=p2022,
            superficie_km2=_float(d.get("sup_km2")),
            poblacion_fuera_gl_2010=max(0, p2010 - suma_2010[codigo]) if p2010 is not None else None,
            poblacion_fuera_gl_2022=max(0, p2022 - suma_2022[codigo]) if p2022 is not None else None,
            synced_at=ahora,
        ))

    # Un gobierno local puede venir en más de una fila (polígono en partes): se
    # juntan sus anillos — la regla par-impar de `geo` los trata igual.
    anillos_por_codigo: dict[str, list] = defaultdict(list)
    for p in poligonos:
        codigo = _codigo(p.get("cgl"))
        if codigo and p["__rings__"]:
            anillos_por_codigo[codigo].extend(p["__rings__"])
    await db.execute(delete(ExtEstPoligono))
    for codigo, anillos in anillos_por_codigo.items():
        db.add(ExtEstPoligono(codigo_indec=codigo, geojson=anillos, synced_at=ahora))

    # Paraguas §3.10 / spec §3.8: superficie y población 2010 en la ficha de
    # Gobierno, que es de donde las leen el rollup y el Tablero.
    locales = (await db.execute(select(ExtGobLocalidad).where(ExtGobLocalidad.deleted_at.is_(None)))).scalars().all()
    for loc in locales:
        valores = filas_gl.get(loc.codigo_indec)
        if valores is None:
            _anomalia(anomalias, tipo="nomenclador_sin_estadistica", codigo=loc.codigo_indec)
            continue
        loc.superficie_km2 = valores.get("superficie_km2")
        loc.poblacion_2010 = valores.get("poblacion_2010")

    await db.flush()
    return leidas, len(filas_gl)


# ── Polígonos para ubicar puntos ──────────────────────────────────────────────

async def _indice(db: AsyncSession) -> IndicePoligonos:
    filas = (await db.execute(select(ExtEstPoligono.codigo_indec, ExtEstPoligono.geojson))).all()
    return IndicePoligonos({f.codigo_indec: f.geojson for f in filas})


# ── Fuente: renabap ───────────────────────────────────────────────────────────

_RENABAP = {
    "id": "ID Renabap",
    "nombre": "Nombre del barrio",
    "familias": "Cantidad de familias que viven en el barrio",
    "anio": "Año de creación del barrio",
    "decada": "Década de creación del barrio",
    "tipologia": "Tipología barrial",
    "dominial": "Situación dominial",
    "energia": "Situación predominante sobre la conexión a la energía eléctrica ",
    "cloacas": "Situación predominante sobre la conexión a la red cloacal",
    "agua": "Situación predominante sobre la conexión a la red de agua",
    "gas": "Situación predominante sobre la conexión a la red de gas",
    "provincia": "Código de provincia",
    "radio": "Código de radio",
    "superficie": "Superficie en km2",
    "lat": "Latitud del centroide",
    "lng": "Longitud del centroide",
}


async def _sync_renabap(db: AsyncSession, client: httpx.AsyncClient, anomalias: list[dict]) -> tuple[int, int]:
    filas = await clientes.renabap_csv(client)
    _validar_campos(filas, list(_RENABAP.values()), "RENABAP")
    cordoba = [f for f in filas if (f.get(_RENABAP["provincia"]) or "").strip() == "14"]
    if not cordoba:
        raise FuenteFallida("RENABAP: no trajo barrios de Córdoba")
    indice = await _indice(db)
    ahora = _now()
    await db.execute(delete(ExtRenabapBarrio))
    guardadas = 0
    vistos: set[str] = set()
    for f in cordoba:
        id_renabap = _texto(f.get(_RENABAP["id"]))
        if not id_renabap or id_renabap in vistos:
            _anomalia(anomalias, tipo="id_invalido_o_repetido", id=id_renabap)
            continue
        vistos.add(id_renabap)
        lat, lng = _float(f.get(_RENABAP["lat"])), _float(f.get(_RENABAP["lng"]))
        anio = _int(f.get(_RENABAP["anio"]))
        db.add(ExtRenabapBarrio(
            id_renabap=id_renabap,
            nombre=_texto(f.get(_RENABAP["nombre"])),
            familias=_int(f.get(_RENABAP["familias"])),
            anio_creacion=anio if anio else None,  # la fuente usa 0 para "sin dato"
            decada_creacion=_texto(f.get(_RENABAP["decada"])),
            tipologia=_texto(f.get(_RENABAP["tipologia"])),
            situacion_dominial=_texto(f.get(_RENABAP["dominial"])),
            energia=_texto(f.get(_RENABAP["energia"])),
            cloacas=_texto(f.get(_RENABAP["cloacas"])),
            agua=_texto(f.get(_RENABAP["agua"])),
            gas=_texto(f.get(_RENABAP["gas"])),
            superficie_km2=_float(f.get(_RENABAP["superficie"])),
            lat=lat,
            lng=lng,
            codigo_radio=_texto(f.get(_RENABAP["radio"])),
            codigo_indec=indice.ubicar(lng, lat),
            version=settings.renabap_version,
            synced_at=ahora,
        ))
        guardadas += 1
    await db.flush()
    return len(cordoba), guardadas


# ── Fuente: idecor_equipamientos ──────────────────────────────────────────────

def _punto(feature: dict) -> tuple[float | None, float | None]:
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates")
    if not coords:
        return None, None
    if geom.get("type") == "MultiPoint":
        coords = coords[0]
    return float(coords[0]), float(coords[1])


def _niveles(raw: Any) -> str | None:
    """`'["1. Común - Primario", "2. Común - Secundario"]'` → texto con `|`."""
    if raw is None:
        return None
    try:
        valores = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(valores, list):
            return " | ".join(str(v) for v in valores if v) or None
    except ValueError:
        pass
    return _texto(raw)


async def _sync_equipamientos(db: AsyncSession, client: httpx.AsyncClient, anomalias: list[dict]) -> tuple[int, int]:
    salud = await clientes.wfs_features(client, "Centros_Salud")
    educacion = await clientes.wfs_features(client, "establecimientos_educativos")
    _validar_campos([f.get("properties", {}) for f in salud], ["codigo_cuie", "establecimiento_salud", "tipologia", "dependencia"], "Centros_Salud")
    _validar_campos([f.get("properties", {}) for f in educacion], ["cueanexo", "nombre", "est_sector", "nivel"], "establecimientos_educativos")
    indice = await _indice(db)
    ahora = _now()
    await db.execute(delete(ExtEquipamiento))
    guardadas = 0
    for tipo, features in (("salud", salud), ("educacion", educacion)):
        for f in features:
            p = f.get("properties") or {}
            lng, lat = _punto(f)
            if lng is None:
                _anomalia(anomalias, tipo="sin_geometria", capa=tipo, codigo=p.get("codigo_cuie") or p.get("cueanexo"))
            if tipo == "salud":
                datos = dict(codigo_fuente=_texto(p.get("codigo_cuie")), nombre=_texto(p.get("establecimiento_salud")),
                             categoria=_texto(p.get("tipologia")), sector=_texto(p.get("dependencia")), ambito=None,
                             localidad_fuente=_texto(p.get("localidad")), departamento_fuente=_texto(p.get("depto")))
            else:
                datos = dict(codigo_fuente=_texto(p.get("cueanexo")), nombre=_texto(p.get("nombre")),
                             categoria=_niveles(p.get("nivel")), sector=_texto(p.get("est_sector")),
                             ambito=_texto(p.get("est_ambito")), localidad_fuente=_texto(p.get("est_localidad")),
                             departamento_fuente=_texto(p.get("est_departamento")))
            db.add(ExtEquipamiento(tipo=tipo, lat=lat, lng=lng, codigo_indec=indice.ubicar(lng, lat), synced_at=ahora, **datos))
            guardadas += 1
    await db.flush()
    return len(salud) + len(educacion), guardadas


# ── Fuente: idecor_vitales ────────────────────────────────────────────────────

async def _sync_vitales(db: AsyncSession, client: httpx.AsyncClient, anomalias: list[dict]) -> tuple[int, int]:
    radios = await clientes.wfs_features(client, "radios_urbanos", propiedades=("nombre", "geom"))
    indice = await _indice(db)
    # Respaldo por nombre: el radio legal de IDECOR puede ser más grande que el
    # polígono censal y su centroide caer afuera (Tanti: 95 km² vs 47 km²). Solo
    # nombres que aparecen una vez en Estadística (hay homónimos entre deptos).
    nombres_est: dict[str, list[str]] = defaultdict(list)
    for codigo_est, nombre_est in (await db.execute(select(ExtEstGobiernoLocal.codigo_indec, ExtEstGobiernoLocal.nombre))).all():
        if nombre_est:
            nombres_est[normalize_name(nombre_est)].append(codigo_est)
    codigo_por_radio: dict[str, str | None] = {}
    for f in radios:
        nombre = _texto((f.get("properties") or {}).get("nombre"))
        if not nombre:
            continue
        c = centroide(f.get("geometry"))
        codigo = indice.ubicar(*c) if c else None
        if codigo is None:
            candidatos = nombres_est.get(normalize_name(nombre), [])
            codigo = candidatos[0] if len(candidatos) == 1 else None
        if nombre in codigo_por_radio and codigo_por_radio[nombre] != codigo:
            _anomalia(anomalias, tipo="radio_homonimo", radio=nombre)
            codigo = None
        codigo_por_radio[nombre] = codigo

    totales: dict[tuple[str, int, str], int] = defaultdict(int)
    leidas = 0
    for tipo, capa in (("nacimientos", "registro_c_nacimientos"), ("defunciones", "registro_c_defunciones")):
        filas = [f.get("properties") or {} for f in await clientes.wfs_features(client, capa, propiedades=("nombre", "total_loc", "anio"), wgs84=False)]
        _validar_campos(filas, ["nombre", "total_loc", "anio"], capa)
        leidas += len(filas)
        for p in filas:
            nombre, anio = _texto(p.get("nombre")), _int(p.get("anio"))
            if not nombre or anio is None:
                continue
            totales[(nombre, anio, tipo)] += _int(p.get("total_loc")) or 0

    ahora = _now()
    await db.execute(delete(ExtEstadisticaVital))
    sin_ubicar: set[str] = set()
    for (nombre, anio, tipo), total in totales.items():
        codigo = codigo_por_radio.get(nombre)
        if codigo is None:
            sin_ubicar.add(nombre)
        db.add(ExtEstadisticaVital(radio_idecor=nombre, anio=anio, tipo=tipo, total=total, codigo_indec=codigo, synced_at=ahora))
    for nombre in sorted(sin_ubicar):
        _anomalia(anomalias, tipo="radio_sin_gobierno_local", radio=nombre)
    await db.flush()
    return leidas, len(totales)


# ── Orquestación ──────────────────────────────────────────────────────────────

_HANDLERS: dict[str, Callable[[AsyncSession, httpx.AsyncClient, list[dict]], Awaitable[tuple[int, int]]]] = {
    "estadistica": _sync_estadistica,
    "renabap": _sync_renabap,
    "idecor_equipamientos": _sync_equipamientos,
    "idecor_vitales": _sync_vitales,
}


async def sync_fuentes(
    db: AsyncSession, fuentes: list[str] | None = None, disparado_por: str = "cloud-scheduler"
) -> list[dict[str, Any]]:
    elegidas = [f for f in FUENTES if not fuentes or f in fuentes]
    resultados = []
    async with clientes._cliente() as client:
        for fuente in elegidas:
            log = ExtFuentesOficialesSyncLog(fuente=fuente, estado="error", iniciado_at=_now(), disparado_por=disparado_por)
            anomalias: list[dict] = []
            try:
                async with db.begin_nested():
                    leidas, guardadas = await _HANDLERS[fuente](db, client, anomalias)
                log.filas_leidas, log.filas_guardadas = leidas, guardadas
                log.estado = "parcial" if anomalias else "ok"
            except Exception as exc:  # noqa: BLE001 — una fuente rota no frena a las demás (spec §4)
                logger.warning("fuentes_oficiales: falló %s: %r", fuente, exc)
                log.mensaje = str(exc)[:2000]
                anomalias = []
            log.anomalias = anomalias or None
            log.finalizado_at = _now()
            db.add(log)
            await db.flush()
            resultados.append({
                "fuente": fuente, "estado": log.estado, "filas_leidas": log.filas_leidas,
                "filas_guardadas": log.filas_guardadas, "anomalias": len(anomalias), "mensaje": log.mensaje,
            })
    return resultados


async def estado_sync(db: AsyncSession) -> list[dict[str, Any]]:
    """Última corrida de cada fuente."""
    resultado = []
    for fuente in FUENTES:
        log = (await db.execute(
            select(ExtFuentesOficialesSyncLog).where(ExtFuentesOficialesSyncLog.fuente == fuente)
            .order_by(ExtFuentesOficialesSyncLog.iniciado_at.desc()).limit(1)
        )).scalar_one_or_none()
        resultado.append({
            "fuente": fuente,
            "estado": log.estado if log else None,
            "iniciado_at": log.iniciado_at if log else None,
            "filas_guardadas": log.filas_guardadas if log else None,
            "mensaje": log.mensaje if log else None,
        })
    return resultado
