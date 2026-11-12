import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.conversaciones import models as _conv_models  # noqa: F401 — registra tablas en Base
from app.conversaciones.router import router as agente_router
from app.database import engine, engine_llm
from app.internal.router import router as internal_router
from app.semantica import models as _ag_models  # noqa: F401

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment == "production" and not settings.llm_database_url:
        log.error("LLM_DATABASE_URL sin configurar: consulta_sql corre con el rol de la app. "
                  "La garantía de solo lectura depende del rol agente_llm (spec §2.3).")
    if settings.proveedor_llm == "anthropic" and not settings.anthropic_api_key:
        log.error("ANTHROPIC_API_KEY sin configurar: el agente no va a poder responder.")
    yield
    await engine.dispose()
    if engine_llm is not engine:
        await engine_llm.dispose()


app = FastAPI(
    title="svc-agente — Agente de consultas",
    description="Agente conversacional de consultas para funcionarios. Ver docs/files/spec-agente-consultas.md (ADR-033).",
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
    log.exception("Error no manejado")
    return JSONResponse(status_code=500, content={"error": {
        "code": "ERROR_INTERNO", "message": "Error interno del servidor", "service": settings.service_name}})


@app.get("/health", tags=["infraestructura"])
async def health_check():
    return {"status": "ok", "service": settings.service_name, "version": "0.1.0"}


app.include_router(agente_router, prefix="/api/v1/agente")
app.include_router(internal_router)
