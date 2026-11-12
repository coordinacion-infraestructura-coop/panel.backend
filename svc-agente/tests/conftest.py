"""Fixtures. SQLite en archivo temporal (no :memory:) para que la sesión de la app y la del rol
LLM usen conexiones distintas, como en producción: el rollback de `consulta_sql` no debe tocar
las escrituras de la app. El schema `ag` es una base SQLite adjunta (app.database)."""
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import database
from app.auth import AuthUser, get_current_user
from app.database import Base, adjuntar_schema_ag_sqlite
from app.main import app

ADMIN = AuthUser(uid="a", email="admin@test.com", role="Admin", secretarias=[])
AUTORIDAD = AuthUser(uid="b", email="autoridad@test.com", role="Autoridad", secretarias=[])
OPERADOR = AuthUser(uid="c", email="operador@test.com", role="Operador", secretarias=["vivienda"])


@pytest_asyncio.fixture
async def engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agente.db'}", poolclass=NullPool)
    adjuntar_schema_ag_sqlite(eng)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sesiones(engine, monkeypatch):
    fabrica = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", fabrica)
    monkeypatch.setattr(database, "LlmSessionLocal", fabrica)
    return fabrica


@pytest_asyncio.fixture
async def db(sesiones):
    async with sesiones() as s:
        yield s


@pytest_asyncio.fixture
async def db_llm(sesiones):
    async with sesiones() as s:
        yield s


@pytest_asyncio.fixture
async def client(sesiones):
    async def _get_db():
        async with sesiones() as s:
            yield s
            await s.commit()

    async def _get_db_llm():
        async with sesiones() as s:
            yield s
            await s.rollback()

    app.dependency_overrides[database.get_db] = _get_db
    app.dependency_overrides[database.get_db_llm] = _get_db_llm
    app.dependency_overrides[get_current_user] = lambda: AUTORIDAD
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def as_user():
    def _set(user: AuthUser):
        app.dependency_overrides[get_current_user] = lambda: user
    return _set


# ── Datos crudos de las fuentes (lo que devuelven los extractores) ───────────

UTC = timezone.utc


def raw_fuentes() -> dict:
    return {
        "vivienda": {
            "localidades": [
                {"id_geo": "G1", "departamento": "San Justo", "localidad": "San Francisco", "lat_centro": -31.42, "lon_centro": -62.08},
                {"id_geo": "G2", "departamento": "San Justo", "localidad": "Morteros", "lat_centro": -30.71, "lon_centro": -62.0},
                {"id_geo": "G3", "departamento": "General San Martín", "localidad": "Villa María", "lat_centro": -32.41, "lon_centro": -63.24},
                {"id_geo": "G4", "departamento": "Río Segundo", "localidad": "Villa del Rosario", "lat_centro": -31.55, "lon_centro": -63.53},
                {"id_geo": "G5", "departamento": "Calamuchita", "localidad": "Villa del Rosario", "lat_centro": -32.0, "lon_centro": -64.5},
            ],
            "alias": [{"id": "al1", "texto_normalizado": "san fco", "departamento_normalizado": "", "id_geo": "G1"}],
            "cc": [
                {"id": "cc1", "nombre": "SAN FRANCISCO", "departamento": "SAN JUSTO", "id_geo": "G1", "monto": 1000000,
                 "cantidad": None, "estado_general": "En ejecución de obra", "fecha_inicio": None,
                 "updated_at": datetime(2026, 1, 10, tzinfo=UTC)},
                {"id": "cc2", "nombre": "Morteros", "departamento": "San Justo", "id_geo": "G2", "monto": 500000,
                 "cantidad": None, "estado_general": "Obra finalizada", "fecha_inicio": None,
                 "updated_at": datetime(2026, 10, 1, tzinfo=UTC)},
            ],
            "ch": [
                {"id": "ch1", "nombre": "Villa María", "departamento": "Gral San Martín", "id_geo": "G3", "monto": 340000000,
                 "cantidad": 10, "estado_general": "Convenio en firma", "fecha_inicio": date(2026, 3, 1),
                 "updated_at": datetime(2026, 3, 2, tzinfo=UTC)},
            ],
            "ml": [],
            "checklist": [{"id": "chk1", "programa": "cc", "entidad_id": "cc1", "estado_expediente": "En obra"}],
            "avance": [
                {"checklist_id": "chk1", "porcentaje": 40, "fecha_medicion": date(2026, 5, 1)},
                {"checklist_id": "chk1", "porcentaje": 70, "fecha_medicion": date(2026, 8, 1)},
            ],
            "hitos": [
                {"id": "h1", "tipo": "anticipo", "fecha_acreditado": date(2026, 2, 1), "programa": "cc", "entidad_id": "cc1"},
                {"id": "h2", "tipo": "40", "fecha_acreditado": date(2026, 6, 1), "programa": "cc", "entidad_id": "cc1"},
                {"id": "h3", "tipo": "70", "fecha_acreditado": None, "programa": "cc", "entidad_id": "cc1"},
                {"id": "h4", "tipo": "anticipo", "fecha_acreditado": None, "programa": "cc", "entidad_id": "borrado"},
            ],
            "hist_cc": [{"id": "hc1", "origen_id": "cc1", "campo": "ejuridico", "anterior": "A", "nuevo": "B",
                         "fecha": datetime(2026, 4, 1, tzinfo=UTC)}],
            "hist_ch": [], "hist_ml": [],
            "hist_checklist": [{"id": "hk1", "programa": "cc", "origen_id": "cc1", "nuevo": "En obra",
                                "fecha": datetime(2026, 5, 1, tzinfo=UTC)}],
        },
        "privada": {
            "gestiones": [
                {"id": "p1", "estado": "INGRESADO", "urgencia": "Alta", "fecha_ingreso": date(2026, 1, 1),
                 "fecha_estado": None, "fecha_finalizacion": None, "id_geo": "G1", "departamento": "SAN JUSTO",
                 "localidad": "S. Francisco", "tipo_gestion": None, "canal_origen": None, "ok_gobernador": "PENDIENTE",
                 "ok_ministro": "PENDIENTE", "costo_estimado": None,
                 "detalle": "Pide ambulancia. Contacto Juan 351-555-1234, DNI 30.123.456, juan@mail.com. Presupuesto $ 1.500.000",
                 "area": "Salud", "ministerio": "Ministerio de Salud", "categoria": "Salud", "categoria_general": None, "programa": None},
                {"id": "p2", "estado": "FINALIZADA", "urgencia": "Media", "fecha_ingreso": date(2026, 2, 1),
                 "fecha_estado": None, "fecha_finalizacion": date(2026, 3, 1), "id_geo": "G1", "departamento": "San Justo",
                 "localidad": "San Francisco", "tipo_gestion": None, "canal_origen": None, "ok_gobernador": "OK",
                 "ok_ministro": "OK", "costo_estimado": 1000, "detalle": "Arreglo de calle",
                 "area": "Obras", "ministerio": None, "categoria": None, "categoria_general": None, "programa": None},
                {"id": "p3", "estado": "DERIVADO A SUAC", "urgencia": "Baja", "fecha_ingreso": date(2026, 10, 20),
                 "fecha_estado": None, "fecha_finalizacion": None, "id_geo": "INEXISTENTE", "departamento": "Calamuchita",
                 "localidad": "Pueblo X", "tipo_gestion": None, "canal_origen": None, "ok_gobernador": "PENDIENTE",
                 "ok_ministro": "PENDIENTE", "costo_estimado": None, "detalle": "Luminarias",
                 "area": "Obras", "ministerio": None, "categoria": None, "categoria_general": None, "programa": None},
            ],
            "eventos": [{"id": "e1", "origen_id": "p2", "anterior": "INGRESADO", "nuevo": "FINALIZADA",
                         "fecha": datetime(2026, 3, 1, tzinfo=UTC)}],
            "padron": [{"id_geo": "G1", "intendente": "Intendente SF", "partido": "Partido A"}],
        },
        "gasifera": {
            "obras": [{"id": "o1", "nombre": "Gasoducto Norte", "departamento": "San Justo", "estado_obra": "EN EJECUCION",
                       "estado_resumen": "En ejecución", "avance": 0.5, "fecha_inicio": date(2025, 6, 1),
                       "monto": 900, "monto_usd": 9, "updated_at": datetime(2026, 9, 1, tzinfo=UTC)}],
            "obras_localidades": [{"obra_id": "o1", "localidad": "San Francisco", "id_geo": "G1"},
                                  {"obra_id": "o1", "localidad": "Morteros", "id_geo": "G2"},
                                  {"obra_id": "o1", "localidad": "Frontera", "id_geo": None}],
            "acciones": [],
            "sync": [{"ultimo": datetime(2026, 11, 4, 10, tzinfo=UTC)}],
        },
        "gralgob": {
            "compromisos": [{"id": "a1", "nombre": "Obra ATP", "departamento": "San Justo", "localidad": "San Francisco",
                             "id_geo": "G1", "monto": 1000, "fecha_inicio": date(2026, 4, 1), "updated_at": None}],
            "cronograma": [{"id": "cr1", "compromiso_id": "a1", "periodo": date(2026, 5, 1), "monto": -400}],
            "interno": [{"id": "i1", "codigo_indec": "140001", "localidad": "SAN FRANCISCO", "departamento": "SAN JUSTO",
                         "fecha": date(2026, 9, 1), "monto": 250}],
            "sync": [{"ultimo": None}],
        },
        "datos_externos": {
            "censo": [{"id_geo": "G1", "codigo_indec": "140001", "poblacion_2022": 70000, "viviendas_2022": 25000},
                      {"id_geo": "G3", "codigo_indec": "140003", "poblacion_2022": 90000, "viviendas_2022": 30000}],
            "transferencias": [
                {"id": "t1", "id_geo": "G1", "departamento": "SAN JUSTO", "localidad": "SAN FRANCISCO", "tipo": "municipio",
                 "concepto": "COPA", "periodo": date(2026, 9, 1), "monto": 100},
                {"id": "t2", "id_geo": "G1", "departamento": "SAN JUSTO", "localidad": "SAN FRANCISCO", "tipo": "municipio",
                 "concepto": "FOFINDES", "periodo": date(2026, 10, 1), "monto": 50},
                # La fuente real trae también la suma como concepto "total": no se carga.
                {"id": "t3", "id_geo": "G1", "departamento": "SAN JUSTO", "localidad": "SAN FRANCISCO", "tipo": "municipio",
                 "concepto": "total", "periodo": date(2026, 10, 1), "monto": 150},
            ],
            "sync": [{"ultimo": datetime(2026, 11, 1, tzinfo=UTC)}],
        },
    }


def lector_de(raw: dict, fallan: set[str] = frozenset()):
    async def _leer(fuente: str):
        if fuente in fallan:
            raise ConnectionError(f"{fuente} caída")
        return raw[fuente]
    return _leer


HOY = date(2026, 11, 5)


@pytest_asyncio.fixture
async def cargado(db):
    """db_agente con la capa semántica cargada desde `raw_fuentes()`."""
    from app.etl.carga import refrescar
    await refrescar(db, lector_de(raw_fuentes()), hoy=HOY)
    await db.commit()
    return db
