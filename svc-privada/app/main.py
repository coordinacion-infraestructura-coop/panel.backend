from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import engine

# Registrar las tablas en Base.metadata (Fase 1 — schema). Los routers llegan en Fase 2.
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


# Fase 2: app.include_router(gestiones_router, prefix="/api/v1/privada", ...)
# Fase 3: app.include_router(internal_router)  # sin prefijo /api/v1
