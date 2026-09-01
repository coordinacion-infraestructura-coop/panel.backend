from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import engine

# Registrar las tablas en Base.metadata.
from app.catalogos.models import (  # noqa: F401
    CatCanalOrigen,
    CatCategoriaGeneral,
    CatEstado,
    CatMinisterioAgencia,
    CatTipoGestion,
    CatUrgencia,
)
from app.gestiones.models import Gestion, GestionEvento  # noqa: F401
from app.territorial.models import DepartamentoInfo, GeoLocalidad, LocalidadInfo  # noqa: F401

from app.catalogos.router import router as catalogos_router
from app.gestiones.router import router as gestiones_router
from app.informe.router import router as informe_router
from app.internal.router import router as internal_router
from app.portal_alias import router as me_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="svc-privada — Secretaría Privada del Ministro",
    description="Gestión de demandas/gestiones. Migrado desde BigQuery (ADR-008).",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://gestorcooperativo.web.app",
        "https://gestorcooperativo.firebaseapp.com",
        "https://ministerio-coop.gob.ar",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "ERROR_INTERNO",
                "message": "Error interno del servidor",
                "service": settings.service_name,
            }
        },
    )


@app.get("/health", tags=["infraestructura"])
async def health_check():
    return {"status": "ok", "service": settings.service_name, "version": "0.1.0"}


_PREFIX = "/api/v1/privada"
app.include_router(me_router, prefix=_PREFIX)
app.include_router(gestiones_router, prefix=_PREFIX)
app.include_router(catalogos_router, prefix=_PREFIX)
app.include_router(informe_router, prefix=_PREFIX)

# IAM-only, sin prefijo /api/v1, sin get_current_user (ADR-015 / E5a).
app.include_router(internal_router)
