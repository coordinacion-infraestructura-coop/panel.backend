from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import engine
from app.programas.router import router as programas_router
from app.beneficiarios.router import router as beneficiarios_router
from app.expedientes.router import router as expedientes_router
from app.asignaciones.router import router as asignaciones_router
from app.cordon_cuneta.router import router as cordon_cuneta_router
from app.cordoba_hogar.router import router as cordoba_hogar_router
from app.portal.router import router as portal_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="svc-vivienda — Secretaría de Vivienda",
    description="Gestión de programas habitacionales: Córdoba Hogar, Mi Lugar, Cordón Cuneta, Loteos.",
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


app.include_router(programas_router, prefix="/api/v1/vivienda", tags=["programas"])
app.include_router(beneficiarios_router, prefix="/api/v1/vivienda", tags=["beneficiarios"])
app.include_router(expedientes_router, prefix="/api/v1/vivienda", tags=["expedientes"])
app.include_router(asignaciones_router, prefix="/api/v1/vivienda", tags=["asignaciones"])
app.include_router(cordon_cuneta_router, prefix="/api/v1/vivienda", tags=["cordon-cuneta"])
app.include_router(cordoba_hogar_router, prefix="/api/v1/vivienda", tags=["cordoba-hogar"])
app.include_router(portal_router, prefix="/api/v1", tags=["portal"])
