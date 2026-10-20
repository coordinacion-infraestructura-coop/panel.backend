from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import engine
from app.internal.router import router as internal_router
from app.tablero.router import router as tablero_router
from app.geo_censo.models import ExtGeoCenso  # noqa: F401 — ensures tables are registered with Base
from app.gobierno.models import ExtGobEnte, ExtGobLocalidad, ExtGobSyncLog  # noqa: F401
from app.gob_transferencias.models import (  # noqa: F401
    ExtGobCopa,
    ExtGobEmpleados,
    ExtGobFodemep,
    ExtGobFodemepEstado,
    ExtGobFofindes,
    ExtGobFommep,
)
from app.transferencias.models import ExtTransferencia, ExtTransferenciaSyncLog  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="svc-datos-externos — Datos de referencia externos",
    description=(
        "Censo 2022 INDEC, transferencias a municipios/comunas y planillas de Gobierno. "
        "Endpoints internos IAM-only (resumen_territorial, syncs, IDECOR) y, por el "
        "API Gateway, el Tablero de Gobierno (ADR-025, ADR-028; "
        "docs/files/spec-tablero-gobierno-panel.md)."
    ),
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


app.include_router(tablero_router, prefix="/api/v1/datos-externos", tags=["tablero-gobierno"])

# Sin prefijo /api/v1 — no pasa por API Gateway, ver app/internal/router.py
app.include_router(internal_router)
