"""Fuentes oficiales públicas por gobierno local
(docs/files/spec-datos-externos-fuentes-oficiales.md §8). Las fuentes se
reemplazan por falsos: ningún test toca la red."""
import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import rollup
from app.fuentes_oficiales import clientes, sync
from app.fuentes_oficiales.geo import IndicePoligonos, centroide
from app.fuentes_oficiales.models import (
    ExtEquipamiento,
    ExtEstadisticaVital,
    ExtEstDepartamento,
    ExtEstGobiernoLocal,
    ExtFuentesOficialesSyncLog,
    ExtRenabapBarrio,
)
from app.gobierno.models import ExtGobLocalidad

# Dos gobiernos locales de juguete, cuadrados de 1°x1°: A en (0..1, 0..1), B en (2..3, 0..1).
CUADRADO_A = [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
CUADRADO_B = [[[2, 0], [3, 0], [3, 1], [2, 1], [2, 0]]]


def _gl(codigo: int, **extra) -> dict:
    return {"código_gobierno_local": codigo, **extra}


def _capas(n_gl: int = 2, *, sin_campo: str | None = None) -> dict[str, list[dict]]:
    """Respuestas por capa. `n_gl` > 2 agrega gobiernos locales de relleno
    para pasar el control de "al menos 400"."""
    codigos = [140001, 140002] + [150000 + i for i in range(n_gl - 2)]
    ficha = []
    for i, c in enumerate(codigos):
        ficha.append(_gl(
            c, gobierno_local=f"GL {c}", código_departamento=7, **{
                "situación_al_año_2022": "MUN", "total_de_población_2010": 1000 + i, "total_de_población_2022": 1500 + i,
                "variación_intercensal": Decimal("0.5"), "superficie_en_km2": Decimal("12.5"), "densidad_poblacional": 120,
                "hogares": 500, "promedio_de_personas_por_hogar": Decimal("3.0"), "niñas_os_y_adolescentes_de_0_a": 25,
                "adultos_mayores__65_y_más____": 12, "coeficiente_de_vejez_demográfic": 14,
            },
        ))
    ficha.append(_gl(14, gobierno_local="PROVINCIA"))  # fila de Provincia: se descarta
    ficha.append(dict(ficha[0]))  # repetida: anomalía
    condvida = [_gl(c, **{campo: Decimal("10") for campo in sync._CONDVIDA.values()}) for c in codigos] + [_gl(14000)]
    pobviv = [{"codgl": c, **{campo: 7 for campo in sync._POBVIV.values()}} for c in codigos]
    educ = [_gl(c, **{campo: 50 for campo in sync._EDUCACION.values()}) for c in codigos]
    salud = [_gl(c, **{campo: 60 for campo in sync._SALUD.values()}) for c in codigos]
    laboral = [{"código_gobierno_local_2": c, "tasa_de_desocupacion": 8, "actividad_principal": "Comercio"} for c in codigos]
    ips = [{"id_2": Decimal(f"{c}.0"), **{campo: Decimal("55.5") for campo in sync._IPS.values()},
            "índice_de_progreso_social__nive": "Bajo"} for c in codigos]
    deptos = [{"link": 14007, "nam_de": "CALAMUCHITA", "pob_2022": 10000 + sum(1500 + i for i in range(n_gl)),
               "pob_2010": 500, "sup_km2": 4600}]
    poligonos = [{"cgl": 140001, "__rings__": CUADRADO_A}, {"cgl": 140002, "__rings__": CUADRADO_B}]
    capas = {
        "ficha": ficha, "condvida": condvida, "pobviv": pobviv, "educacion": educ, "salud": salud,
        "laboral": laboral, "ips": ips, "departamentos": deptos, "poligonos": poligonos,
    }
    if sin_campo:
        for fila in capas["condvida"]:
            fila.pop(sin_campo, None)
    return capas


class Fuentes:
    def __init__(self, capas: dict, *, renabap_falla: bool = False):
        self.capas = capas
        self.renabap_falla = renabap_falla
        self.por_setting = {
            getattr(sync.settings, f"est_capa_{k}"): k
            for k in ("ficha", "condvida", "pobviv", "educacion", "salud", "laboral", "ips", "departamentos", "poligonos")
        }

    async def arcgis_query(self, client, capa, *, geometria=False):
        return [dict(f) for f in self.capas[self.por_setting[capa]]]

    async def wfs_features(self, client, capa, *, propiedades=None, wgs84=True):
        if capa == "Centros_Salud":
            return [{"properties": {"codigo_cuie": "X1", "establecimiento_salud": "Hosp", "tipologia": "CSM",
                                    "dependencia": "MUNICIPAL"}, "geometry": {"type": "Point", "coordinates": [0.5, 0.5]}}]
        if capa == "establecimientos_educativos":
            return [
                {"properties": {"cueanexo": 1, "nombre": "Esc", "est_sector": "Estatal", "nivel": '["1. Común - Primario"]'},
                 "geometry": {"type": "Point", "coordinates": [2.5, 0.5]}},
                {"properties": {"cueanexo": 2, "nombre": "Rural", "est_sector": "Estatal", "nivel": "[]"},
                 "geometry": {"type": "Point", "coordinates": [9, 9]}},
            ]
        if capa == "radios_urbanos":
            return [{"properties": {"nombre": "GL A"}, "geometry": {"type": "MultiPolygon", "coordinates": [CUADRADO_A]}}]
        if capa == "registro_c_nacimientos":
            return [{"properties": {"nombre": "GL A", "total_loc": 10, "anio": 2024}},
                    {"properties": {"nombre": "GL A", "total_loc": 12, "anio": 2025}},
                    {"properties": {"nombre": "OTRO", "total_loc": 1, "anio": 2025}}]
        if capa == "registro_c_defunciones":
            return [{"properties": {"nombre": "GL A", "total_loc": 4, "anio": 2025}}]
        raise AssertionError(capa)

    async def renabap_csv(self, client):
        if self.renabap_falla:
            raise clientes.FuenteFallida("Poblaciones caído")
        base = {campo: "" for campo in sync._RENABAP.values()}
        return [
            {**base, "ID Renabap": "1", "Nombre del barrio": "B1", "Cantidad de familias que viven en el barrio": "40",
             "Código de provincia": "14", "Año de creación del barrio": "0", "Latitud del centroide": "0.5",
             "Longitud del centroide": "0.5"},
            {**base, "ID Renabap": "2", "Nombre del barrio": "B2", "Cantidad de familias que viven en el barrio": "10",
             "Código de provincia": "14", "Latitud del centroide": "9", "Longitud del centroide": "9"},
            {**base, "ID Renabap": "3", "Código de provincia": "06"},  # otra provincia: se ignora
        ]


async def _correr(db: AsyncSession, fuentes: Fuentes, pedidas=None):
    with patch.object(clientes, "arcgis_query", new=fuentes.arcgis_query), \
         patch.object(clientes, "wfs_features", new=fuentes.wfs_features), \
         patch.object(clientes, "renabap_csv", new=fuentes.renabap_csv):
        return await sync.sync_fuentes(db, pedidas, disparado_por="test")


@pytest.fixture
async def nomenclador(db_session: AsyncSession):
    for codigo, id_geo in (("140001", "100"), ("140002", "200")):
        db_session.add(ExtGobLocalidad(codigo_indec=codigo, nombre_gob=f"GL {codigo}", departamento_gob="CALAMUCHITA",
                                       codigo_dpto_indec="14007", id_geo=id_geo))
    await db_session.flush()


# ─── Geo ──────────────────────────────────────────────────────────────────────

def test_ubicar_punto_y_agujero():
    con_agujero = [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]]
    indice = IndicePoligonos({"A": con_agujero})
    assert indice.ubicar(3, 3) == "A"
    assert indice.ubicar(1.5, 1.5) is None  # en el agujero
    assert indice.ubicar(9, 9) is None
    assert indice.ubicar(None, 1) is None


def test_centroide_del_poligono_mas_grande():
    assert centroide({"type": "MultiPolygon", "coordinates": [CUADRADO_A, [[[10, 10], [10.1, 10], [10.1, 10.1], [10, 10]]]]}) == pytest.approx((0.5, 0.5))


# ─── Estadística ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_estadistica_carga_gobiernos_locales_departamentos_y_ficha(db_session: AsyncSession, nomenclador):
    res = await _correr(db_session, Fuentes(_capas(427)), ["estadistica"])
    assert res[0]["estado"] == "parcial"  # fila repetida
    assert res[0]["filas_guardadas"] == 427
    gl = await db_session.get(ExtEstGobiernoLocal, "140001")
    assert gl.poblacion_2010 == 1000 and gl.poblacion_2022 == 1500
    assert gl.variacion_intercensal == 0.5
    assert gl.codigo_dpto_indec == "14007"
    assert gl.nbi_pct == 10 and gl.hogares_hacinamiento == 7
    assert gl.ips_valor == 55.5 and gl.ips_nivel == "Bajo"  # código del IPS como decimal 140001.0
    assert gl.crudo["ficha"]["gobierno_local"] == "GL 140001"
    assert await db_session.get(ExtEstGobiernoLocal, "14") is None
    depto = await db_session.get(ExtEstDepartamento, "14007")
    assert depto.poblacion_fuera_gl_2022 == 10000
    assert depto.poblacion_fuera_gl_2010 == 0  # nunca negativa
    loc = await db_session.get(ExtGobLocalidad, "140001")
    assert float(loc.superficie_km2) == 12.5 and loc.poblacion_2010 == 1000


@pytest.mark.asyncio
async def test_estadistica_campo_faltante_falla_y_no_toca_lo_anterior(db_session: AsyncSession, nomenclador):
    await _correr(db_session, Fuentes(_capas(427)), ["estadistica"])
    res = await _correr(db_session, Fuentes(_capas(427, sin_campo="tenencia_de_servicios___gas_de")), ["estadistica"])
    assert res[0]["estado"] == "error"
    assert "gas_de" in res[0]["mensaje"]
    assert (await db_session.get(ExtEstGobiernoLocal, "140001")).gas_red_pct == 10


@pytest.mark.asyncio
async def test_estadistica_con_pocas_filas_falla(db_session: AsyncSession):
    res = await _correr(db_session, Fuentes(_capas(2)), ["estadistica"])
    assert res[0]["estado"] == "error"


# ─── Puntos y fuentes independientes ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_todas_las_fuentes_ubican_puntos_y_una_falla_no_frena_a_las_otras(db_session: AsyncSession, nomenclador):
    res = await _correr(db_session, Fuentes(_capas(427), renabap_falla=True))
    estados = {r["fuente"]: r["estado"] for r in res}
    assert estados == {"estadistica": "parcial", "renabap": "error", "idecor_equipamientos": "ok", "idecor_vitales": "parcial"}

    equip = {e.nombre: e.codigo_indec for e in (await db_session.execute(select(ExtEquipamiento))).scalars()}
    assert equip == {"Hosp": "140001", "Esc": "140002", "Rural": None}
    vitales = (await db_session.execute(select(ExtEstadisticaVital).where(ExtEstadisticaVital.radio_idecor == "GL A"))).scalars().all()
    assert {(v.anio, v.tipo, v.total, v.codigo_indec) for v in vitales} == {
        (2024, "nacimientos", 10, "140001"), (2025, "nacimientos", 12, "140001"), (2025, "defunciones", 4, "140001"),
    }
    logs = (await db_session.execute(select(ExtFuentesOficialesSyncLog))).scalars().all()
    assert len(logs) == 4


@pytest.mark.asyncio
async def test_renabap_filtra_cordoba_y_ubica(db_session: AsyncSession, nomenclador):
    await _correr(db_session, Fuentes(_capas(427)), ["estadistica"])
    res = await _correr(db_session, Fuentes(_capas(427)), ["renabap"])
    assert res[0]["estado"] == "ok" and res[0]["filas_guardadas"] == 2
    b1 = await db_session.get(ExtRenabapBarrio, "1")
    assert b1.codigo_indec == "140001" and b1.familias == 40 and b1.anio_creacion is None
    assert (await db_session.get(ExtRenabapBarrio, "2")).codigo_indec is None


# ─── Rollup ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rollup_incluye_indicadores_y_zonas_rurales_del_censo(db_session: AsyncSession, nomenclador):
    await _correr(db_session, Fuentes(_capas(427)))
    filas = {r["id_geo"]: r for r in await rollup.rollup_territorial(db_session)}
    a = filas["100"]
    assert a["superficie_km2"] == 12.5 and a["poblacion_2010"] == 1000
    ind = a["indicadores"]
    assert ind["nbi_pct"] == 10 and ind["calidad_iii_iv_pct"] == 20
    assert ind["renabap_barrios"] == 1 and ind["renabap_familias"] == 40
    assert ind["establecimientos_salud"] == 1 and ind["establecimientos_educativos"] == 0
    assert (ind["vitales_anio"], ind["nacimientos"], ind["defunciones"]) == (2025, 12, 4)
    assert filas["200"]["indicadores"]["establecimientos_educativos"] == 1

    zonas = await rollup.zonas_rurales(db_session)
    assert zonas == [{"departamento": "CALAMUCHITA", "poblacion_2022": 10000, "poblacion_2010": 0, "fuente": "censo"}]


@pytest.mark.asyncio
async def test_zonas_rurales_sin_censo_cae_a_gobierno(db_session: AsyncSession):
    assert await rollup.zonas_rurales(db_session) == []


# ─── Endpoint ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_endpoint_deshabilitado_503(client: AsyncClient):
    resp = await client.post("/internal/datos-externos/fuentes-oficiales/sync")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_endpoint_502_si_fallan_todas_y_422_fuente_invalida(client: AsyncClient):
    with patch.object(sync.settings, "fuentes_oficiales_sync_enabled", True):
        r = await client.post("/internal/datos-externos/fuentes-oficiales/sync", params={"fuentes": "otra"})
        assert r.status_code == 422
        falla = clientes.FuenteFallida("caído")

        async def rota(*a, **k):
            raise falla
        with patch.object(clientes, "arcgis_query", new=rota), patch.object(clientes, "wfs_features", new=rota), \
             patch.object(clientes, "renabap_csv", new=rota):
            r = await client.post("/internal/datos-externos/fuentes-oficiales/sync")
    assert r.status_code == 502
    assert {f["estado"] for f in r.json()["fuentes"]} == {"error"}
    estado = await client.get("/internal/datos-externos/fuentes-oficiales/sync-estado")
    assert [e["estado"] for e in estado.json()] == ["error"] * 4
