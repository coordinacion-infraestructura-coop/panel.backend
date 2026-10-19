"""Valuación de parcelas desde IDECOR (spec-mi-lugar-valor-fiscal-idecor.md §7).
El WFS se reemplaza por un falso que responde según capa y filtro CQL."""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.catastro import idecor, service
from app.catastro.schemas import ValuacionRequest


def _parcela(nom: str, *, valuacion: str, tierra_u: str = "0", tierra_r: str = "0", mejoras: str = "0",
             sup_u: int = 0, sup_r: int = 0, tipo: str = "URBANO") -> dict:
    return {
        "properties": {
            "Nomenclatura": nom, "Nro_Cuenta": 123, "Tipo_Parcela": tipo, "Estado": "BALDIO",
            "desig_oficial": None, "localidad": "VILLA MARIA",
            "Valuacion": Decimal(valuacion), "Valuacion_Tierra_Urbana": Decimal(tierra_u),
            "Valuacion_Tierra_Rural": Decimal(tierra_r), "Valuacion_Mejoras": Decimal(mejoras),
            "Superficie_Tierra_Urbana": sup_u, "Superficie_Tierra_Rural": sup_r,
            "vigencia_desde": "2025-11-06T00:00:00Z",
        },
        "geometry": {"type": "MultiPolygon", "coordinates": [[[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]]},
    }


URB_A = _parcela("1604220301275100", valuacion="2401670179.86", tierra_u="2401670179.86", sup_u=297377)
URB_B = _parcela("1604220301275001", valuacion="1446876490.5", tierra_u="1446876490.5", sup_u=150489)
RUR = _parcela("1304021120362800", valuacion="962201842.54", tierra_r="682465288.3", mejoras="279736554.24",
               sup_r=190000, tipo="RURAL")


class FalsoWFS:
    """Respuestas por (capa, contenido del filtro). Un punto cae en una
    parcela según el orden en que se consulta (`puntos`)."""

    def __init__(self, puntos: list[list[dict]], nomenclaturas: dict[str, list[dict]],
                 vut: dict[str, str | None] | None = None, vur: str | None = None, mapa_falla: bool = False):
        self.puntos = list(puntos)
        self.nomenclaturas = nomenclaturas
        self.vut = vut or {}
        self.vur = vur
        self.mapa_falla = mapa_falla

    async def get_features(self, client, capa, cql, propiedades):
        if capa == "parcelas" and cql.startswith("INTERSECTS"):
            return self.puntos.pop(0)
        if capa == "parcelas":
            return self.nomenclaturas.get(cql.split("'")[1], [])
        if self.mapa_falla:
            raise idecor.CatastroFallido("mapa caído")
        if capa.startswith("valor_tierra_urbana"):
            nom = cql.split("'")[1]
            return [{"properties": {"nomenclatura": nom, "vut_pesos": self.vut[nom]}}] if nom in self.vut else []
        if capa.startswith("valor_tierra_rural"):
            return [{"properties": {"vur_pesos": self.vur}}] if self.vur is not None else []
        raise AssertionError(capa)


def _con(falso: FalsoWFS, anio: int | None = 2025):
    return (
        patch.object(idecor, "get_features", new=falso.get_features),
        patch.object(idecor, "anio_mapa_valores", new=AsyncMock(return_value=anio)),
    )


async def _valuar(falso: FalsoWFS, anio: int | None = 2025, **req):
    p1, p2 = _con(falso, anio)
    with p1, p2:
        return await service.valuar(ValuacionRequest(**req))


@pytest.mark.asyncio
async def test_suma_valuacion_al_centavo_y_mercado_urbano():
    falso = FalsoWFS([[URB_A], [URB_B]], {}, vut={"1604220301275100": Decimal("57687"), "1604220301275001": Decimal("68675")})
    r = await _valuar(falso, puntos=[{"lat": -32.4, "lng": -63.2}, {"lat": -32.41, "lng": -63.21}])
    assert r.valor_total == Decimal("3848546670.36")
    assert r.valor_mercado == Decimal("57687") * 297377 + Decimal("68675") * 150489
    assert r.mercado_anio == 2025
    assert r.vigencia_desde.isoformat() == "2025-11-06"
    assert all(p.origen == "punto" for p in r.parcelas)


@pytest.mark.asyncio
async def test_mercado_rural_usa_pesos_por_hectarea_y_mejoras_suman_al_fiscal():
    falso = FalsoWFS([[RUR]], {}, vur=Decimal("53566500"))
    r = await _valuar(falso, puntos=[{"lat": -31.29, "lng": -64.17}])
    assert r.valor_total == Decimal("962201842.54")
    assert r.valor_mejoras == Decimal("279736554.24")
    assert r.valor_mercado == Decimal("53566500") * 19  # 190.000 m² = 19 ha


@pytest.mark.asyncio
async def test_une_puntos_y_nomenclaturas_sin_repetir_y_normaliza():
    falso = FalsoWFS([[URB_A]], {"1604220301275100": [URB_A], "1604220301275001": [URB_B]})
    r = await _valuar(falso, puntos=[{"lat": -32.4, "lng": -63.2}],
                      nomenclaturas=["1604-2203-0127-5100", "16042203 01275001", "1604220301275001"])
    origenes = {p.nomenclatura: p.origen for p in r.parcelas}
    assert origenes == {"1604220301275100": "ambos", "1604220301275001": "nomenclatura"}
    assert r.valor_total == Decimal("3848546670.36")


@pytest.mark.asyncio
async def test_punto_sin_parcela_y_nomenclatura_inexistente():
    falso = FalsoWFS([[]], {})
    r = await _valuar(falso, puntos=[{"lat": -32.4, "lng": -63.2}], nomenclaturas=["999"])
    assert r.parcelas == []
    assert len(r.puntos_sin_parcela) == 1
    assert r.nomenclaturas_no_encontradas == ["999"]
    assert r.valor_total == Decimal("0.00")
    assert r.valor_mercado is None


@pytest.mark.asyncio
async def test_mapa_de_valores_caido_devuelve_el_fiscal_igual():
    falso = FalsoWFS([[URB_A]], {}, mapa_falla=True)
    r = await _valuar(falso, puntos=[{"lat": -32.4, "lng": -63.2}])
    assert r.valor_total == Decimal("2401670179.86")
    assert r.valor_mercado is None
    assert r.mercado_anio is None
    assert r.mercado_parcelas_sin_valor == 1


@pytest.mark.asyncio
async def test_parcela_sin_valor_en_el_mapa_se_cuenta():
    falso = FalsoWFS([[URB_A], [URB_B]], {}, vut={"1604220301275100": Decimal("57687")})
    r = await _valuar(falso, puntos=[{"lat": -32.4, "lng": -63.2}, {"lat": -32.41, "lng": -63.21}])
    assert r.mercado_parcelas_sin_valor == 1
    assert r.valor_mercado == Decimal("57687") * 297377


@pytest.mark.asyncio
async def test_esquema_cambiado_falla_entero():
    rota = {"properties": {"Nomenclatura": "1", "Valuacion": 1}}
    falso = FalsoWFS([[rota]], {})
    with pytest.raises(idecor.CatastroFallido):
        await _valuar(falso, puntos=[{"lat": -32.4, "lng": -63.2}])


def test_punto_interior_es_el_centroide():
    assert idecor.punto_interior(URB_A["geometry"]) == pytest.approx((5.0, 5.0))


@pytest.mark.asyncio
async def test_anio_mapa_valores_toma_el_mayor_con_las_dos_capas():
    caps = (b"<Name>idecor:valor_tierra_urbana_2024</Name><Name>idecor:valor_tierra_rural_2024</Name>"
            b"<Name>idecor:valor_tierra_urbana_2025</Name><Name>idecor:valor_tierra_rural_2025</Name>"
            b"<Name>idecor:valor_tierra_urbana_2026</Name>")
    idecor._cache_anio = None
    with patch.object(idecor, "_get", new=AsyncMock(return_value=caps)):
        assert await idecor.anio_mapa_valores(None) == 2025
    idecor._cache_anio = None


@pytest.mark.asyncio
async def test_endpoint_502_si_falla_la_fuente(client: AsyncClient):
    with patch("app.catastro.service.valuar", new=AsyncMock(side_effect=idecor.CatastroFallido("caído"))):
        resp = await client.post("/internal/datos-externos/catastro/valuacion", json={"nomenclaturas": ["1"]})
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "CATASTRO_FALLIDO"


@pytest.mark.asyncio
async def test_endpoint_exige_al_menos_un_elemento(client: AsyncClient):
    resp = await client.post("/internal/datos-externos/catastro/valuacion", json={})
    assert resp.status_code == 422
