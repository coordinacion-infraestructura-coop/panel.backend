"""Sync de inscriptos al Congreso de Formación Digital 2026 -> Planificación
(docs/files/spec-privada-sync-capacitacion.md §10). Planilla mockeada."""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.capacitacion import sync
from app.capacitacion.models import CapacitacionInscripcion
from app.integrations.google_sheets import SheetReadError
from app.planificacion.models import PlanEstado, PlanHistorial, PlanLocalidad
from app.territorial.models import GeoLocalidad

URL = "/internal/privada/capacitacion/sync"
PLAN = "/api/v1/privada/planificacion"
R_RESP = "'Respuestas de formulario 1'!A:F"
R_LISTA = "Lista!A:B"

HEADER = ["Marca temporal", "Dirección de correo electrónico", "APELLIDO", "NOMBRE", "LOCALIDAD", "CARGO"]
LISTA = [
    ["DEPARTAMENTO", "LOCALIDAD"],
    ["CALAMUCHITA", "EMBALSE"],
    ["CALAMUCHITA", "PARQUE CALMAYO"],      # vínculo manual -> 2
    ["PTE. ROQUE SAENZ PEÑA", "LABOULAYE"],  # departamento con punto
    ["COLON", "AGUA DE ORO"],
    ["CRUZ DEL EJE", "LOS CHAÑARITOS (C. D. E.)"],
]
# 46345.5 = 2026-11-19 12:00 (serie de Sheets)
T = 46345.5


def _fila(t, email, ape, nom, loc, cargo):
    return [t, email, ape, nom, loc, cargo]


@pytest.fixture
async def padron(db_session):
    db_session.add_all([
        GeoLocalidad(id_geo="1", departamento="CALAMUCHITA", localidad="EMBALSE", activo=True),
        GeoLocalidad(id_geo="2", departamento="CALAMUCHITA", localidad="CALMAYO", activo=True),
        GeoLocalidad(id_geo="130", departamento="PTE ROQUE SAENZ PEÑA", localidad="LABOULAYE", activo=True),
        GeoLocalidad(id_geo="22", departamento="COLÓN", localidad="AGUA DE ORO", activo=True),
    ])
    await db_session.flush()


def _planilla(filas, lista=LISTA):
    return patch(
        "app.integrations.google_sheets.leer_rangos",
        new=AsyncMock(return_value={R_RESP: [HEADER, *filas], R_LISTA: lista}),
    )


async def _filas_plan(client, pid):
    body = (await client.get(f"{PLAN}/programas/{pid}/localidades")).json()
    return {f["id_geo"]: f for f in body["filas"]} if "filas" in body else {f["id_geo"]: f for f in body["localidades"]}


async def _estados(db_session, pid):
    return {e.id: e.nombre for e in (await db_session.execute(select(PlanEstado).where(PlanEstado.programa_id == pid))).scalars()}


async def _pl(db_session, pid):
    return {p.id_geo: p for p in (await db_session.execute(select(PlanLocalidad).where(PlanLocalidad.programa_id == pid))).scalars()}


async def test_alta_inicial_crea_programa_columnas_y_estados(client, db_session, padron):
    filas = [
        _fila(T, "a@x.com", "Pérez", "Ana", "EMBALSE", "Intendente"),
        _fila(T + 0.01, "b@x.com", "Gómez", "Beto", "EMBALSE", "Equipo de comunicación"),
        _fila(T + 0.02, "c@x.com", "Ruiz", "Caro", "PARQUE CALMAYO", "Jefe comunal"),
        _fila(T + 0.03, "d@x.com", "Sosa", "Dani", "LABOULAYE", "Legislador"),
    ]
    with _planilla(filas):
        r = await client.post(URL)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["personas"] == 4 and res["localidades_con_inscriptos"] == 3 and res["localidades_solo_lider"] == 1
    assert res["sin_resolver"] == []
    pid = res["programa_id"]

    cols = (await client.get(f"{PLAN}/programas/{pid}/columnas")).json()
    visibles = [c["clave"] for c in cols if c["visible"]]
    assert visibles == sync.CLAVES_AUTO  # las 4 por defecto quedan ocultas

    estados = await _estados(db_session, pid)
    pl = await _pl(db_session, pid)
    assert estados[pl["1"].estado_id] == "Con inscriptos"
    assert estados[pl["2"].estado_id] == "Solo intendente / jefe comunal"
    assert estados[pl["130"].estado_id] == "Con inscriptos"  # un legislador cuenta (usuario, 2026-11-24)
    assert pl["1"].valores["insc_total"] == 2 and pl["1"].valores["insc_lider"] is True
    assert pl["1"].valores["insc_equipo"] == 1
    assert pl["1"].valores["insc_nombres"] == "GÓMEZ, Beto (Equipo de comunicación); PÉREZ, Ana (Intendente)"
    assert pl["1"].valores["insc_ultima"] == "2026-11-19"
    assert pl["130"].valores["insc_otros"] == 1 and pl["130"].valores["insc_lider"] is False
    assert "22" not in pl  # sin inscriptos: sin fila

    # El correo no se guarda, solo su hash.
    insc = (await db_session.execute(select(CapacitacionInscripcion))).scalars().all()
    assert len(insc) == 4 and all("@" not in i.email_hash and len(i.email_hash) == 64 for i in insc)


async def test_segunda_corrida_sin_cambios_no_escribe_historial(client, db_session, padron):
    filas = [_fila(T, "a@x.com", "Pérez", "Ana", "EMBALSE", "Intendente")]
    with _planilla(filas):
        pid = (await client.post(URL)).json()["programa_id"]
        n = len((await db_session.execute(select(PlanHistorial))).scalars().all())
        res = (await client.post(URL)).json()
    assert res["filas_planificacion_cambiadas"] == 0
    assert len((await db_session.execute(select(PlanHistorial))).scalars().all()) == n
    # Y el programa no se duplica.
    progs = (await client.get(f"{PLAN}/programas")).json()
    assert [p["id"] for p in progs if p["nombre"] == sync.PROGRAMA_NOMBRE] == [pid]


async def test_deduplica_por_correo_con_la_ultima_respuesta(client, db_session, padron):
    filas = [
        _fila(T, "A@x.com ", "Pérez", "Ana", "AGUA DE ORO", "Intendente"),
        _fila(T + 0.1, "a@x.com", "Pérez", "Ana", "EMBALSE", "Intendente"),  # se corrigió la localidad
    ]
    with _planilla(filas):
        res = (await client.post(URL)).json()
    assert res["respuestas_leidas"] == 2 and res["personas"] == 1
    pl = await _pl(db_session, res["programa_id"])
    assert set(pl) == {"1"}


async def test_pasa_de_solo_lider_a_con_inscriptos_y_se_vacia(client, db_session, padron):
    lider = _fila(T, "a@x.com", "Pérez", "Ana", "EMBALSE", "Intendente")
    equipo = _fila(T + 0.1, "b@x.com", "Gómez", "Beto", "EMBALSE", "Equipo de comunicación")
    with _planilla([lider]):
        pid = (await client.post(URL)).json()["programa_id"]
    estados = await _estados(db_session, pid)
    assert estados[(await _pl(db_session, pid))["1"].estado_id] == "Solo intendente / jefe comunal"
    with _planilla([lider, equipo]):
        await client.post(URL)
    assert estados[(await _pl(db_session, pid))["1"].estado_id] == "Con inscriptos"
    with _planilla([]):  # se borraron las respuestas
        await client.post(URL)
    fila = (await _pl(db_session, pid))["1"]
    assert fila.estado_id is None
    assert all(fila.valores.get(k) is None for k in sync.CLAVES_AUTO)
    insc = (await db_session.execute(select(CapacitacionInscripcion))).scalars().all()
    assert all(i.deleted_at is not None for i in insc)


async def test_no_pisa_un_estado_manual(client, db_session, padron):
    filas = [_fila(T, "a@x.com", "Pérez", "Ana", "EMBALSE", "Intendente")]
    with _planilla([]):
        pid = (await client.post(URL)).json()["programa_id"]
    manual = (await client.post(f"{PLAN}/programas/{pid}/estados", json={"nombre": "Contactada"})).json()["id"]
    r = await client.patch(f"{PLAN}/programas/{pid}/localidades/1", json={"updated_at": None, "estado_id": manual})
    assert r.status_code == 200, r.text
    with _planilla(filas):
        await client.post(URL)
    fila = (await _pl(db_session, pid))["1"]
    assert fila.estado_id == manual
    assert fila.valores["insc_total"] == 1  # las columnas automáticas sí se actualizan


async def test_otra_localidad_y_ambiguas_quedan_sin_resolver(client, db_session, padron):
    filas = [
        _fila(T, "a@x.com", "Pérez", "Ana", "OTRA LOCALIDAD", "Jefe comunal"),
        _fila(T, "b@x.com", "Gómez", "Beto", "LOS CHAÑARITOS (C. D. E.)", "Intendente"),  # no está en el padrón de test
    ]
    with _planilla(filas):
        res = (await client.post(URL)).json()
    assert res["personas_sin_localidad_oficial"] == 2
    assert {s["localidad"] for s in res["sin_resolver"]} == {"OTRA LOCALIDAD", "LOS CHAÑARITOS (C. D. E.)"}
    insc = (await db_session.execute(select(CapacitacionInscripcion))).scalars().all()
    assert len(insc) == 2 and all(i.id_geo is None for i in insc)


async def test_dry_run_no_escribe(client, db_session, padron):
    filas = [_fila(T, "a@x.com", "Pérez", "Ana", "EMBALSE", "Intendente")]
    with _planilla(filas):
        res = (await client.post(URL, params={"dry_run": "true"})).json()
    assert res["dry_run"] is True and res["programa_id"] is None and res["filas_planificacion_cambiadas"] == 1
    assert (await db_session.execute(select(CapacitacionInscripcion))).scalars().all() == []


async def test_planilla_ilegible_502(client, padron):
    with patch("app.integrations.google_sheets.leer_rangos", new=AsyncMock(side_effect=SheetReadError("403"))):
        r = await client.post(URL)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "PLANILLA_NO_DISPONIBLE"


async def test_falta_columna_502(client, padron):
    with patch("app.integrations.google_sheets.leer_rangos",
               new=AsyncMock(return_value={R_RESP: [["Marca temporal", "APELLIDO"]], R_LISTA: LISTA})):
        r = await client.post(URL)
    assert r.status_code == 502


def test_vinculacion_manual_sin_ids_repetidos():
    ids = list(sync.VINCULACION_MANUAL.values())
    assert len(ids) == len(set(ids))
