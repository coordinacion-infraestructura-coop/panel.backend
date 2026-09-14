"""Schemas de los endpoints internos (IAM-only) de svc-privada.

Separados de `app/gestiones/schemas.py` porque no son el contrato público
`/api/v1/privada/**` — son el contrato interno cross-servicio (ADR-020).
"""
from typing import Literal

from pydantic import BaseModel, Field

CasoTipo = Literal["cc", "ch", "ml"]
OkEstadoSync = Literal["SI", "PENDIENTE"]
ResultadoSync = Literal["LINKED_NEW", "LINKED_EXISTING", "PENDING_REVIEW", "ERROR"]


class GestionSyncFromVivienda(BaseModel):
    """Payload de `POST /internal/privada/gestiones/sync` — lo manda svc-vivienda
    desde `app/integrations/privada_sync.py` al crear/editar un caso de Cordón
    Cuneta, Córdoba Hogar o Mi Lugar. Ver `docs/files/spec-vinculacion-vivienda-privada.md`.
    """

    caso_tipo: CasoTipo
    caso_id: str = Field(min_length=1, max_length=36)
    id_legacy: str = Field(min_length=1, max_length=100)

    nro_expediente: str | None = None
    localidad: str = Field(min_length=1)
    departamento: str = Field(min_length=1)

    categoria_id: int | None = None
    programa_id: int | None = None
    area_id: int | None = None
    ministerio_agencia_id: str | None = None
    ok_gobernador: OkEstadoSync = "PENDIENTE"
    ok_ministro: OkEstadoSync = "PENDIENTE"

    detalle: str | None = None


class GestionSyncResult(BaseModel):
    resultado: ResultadoSync
    id_legacy: str
    gestion_id: str | None = None
    motivo: str | None = None
    candidatos: list[str] | None = None
    diff: dict[str, dict[str, str | int | None]] | None = None
