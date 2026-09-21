from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.atp.models import (  # noqa: F401 — ensures tables are registered with Base
    AtpCompromiso,
    AtpCronogramaPago,
    AtpSyncLog,
)
from app.atp.router import router as atp_router
from app.config import settings
from app.database import engine
from app.internal.router import router as internal_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="svc-gralgob — Secretaría General de Gobierno",
    description=(
        "Fase 0: espejo de solo lectura de la hoja 'BD' del Sheet "
        "'ATP - Compromiso Gobernador' + panel preliminar de solo lectura "
        "sobre esos datos. Sin panel de negocio editable todavía — ver "
        "docs/files/spec-sync-atp-compromiso-gobernador.md y "
        "docs/files/spec-svc-gralgob.md."
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


app.include_router(atp_router, prefix="/api/v1/gralgob", tags=["gralgob"])

# Sin prefijo /api/v1 — no pasa por API Gateway, ver app/internal/router.py
app.include_router(internal_router)
