from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import engine
from app.internal.router import router as internal_router
from app.geo_censo.models import ExtGeoCenso  # noqa: F401 — ensures tables are registered with Base
from app.transferencias.models import ExtTransferencia, ExtTransferenciaSyncLog  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="svc-datos-externos — Datos de referencia externos",
    description=(
        "Censo 2022 INDEC a nivel gobierno local + transferencias automáticas "
        "a municipios/comunas. Sin panel de negocio ni endpoints públicos — "
        "solo endpoints internos IAM-only consumidos por resumen_territorial "
        "de svc-vivienda. Ver docs/files/spec-resumen-territorial-tablero-v2.md (ADR-025)."
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


# Sin prefijo /api/v1 — no pasa por API Gateway, ver app/internal/router.py
app.include_router(internal_router)
