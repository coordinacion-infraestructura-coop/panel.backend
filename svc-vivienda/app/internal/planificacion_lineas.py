"""Lectura de las filas de CC/CH/ML para la planificación de programas de svc-privada
(ADR-036, docs/files/spec-privada-planificacion-programas.md §6).

**Sólo lectura**: no agrega tablas, migraciones ni escrituras. Lo expone
`GET /internal/planificacion/lineas` (IAM-only, sólo `svc-privada@`). Lee en vivo de
`db_vivienda` (como ADR-030), no del snapshot de `resumen_territorial`: el snapshot filtra por
secretaría y no trae ni `ok_gob` ni la fecha de firma del convenio.

Una fila por entidad no borrada. Puede haber más de una por `id_geo` (Vivienda carga filas con el
nombre de la localidad modificado para distinguir programas), así que el caller las agrupa. Las
filas sin `localidad_id` se cuentan en `sin_id_geo` para que no se pierdan en silencio.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cordoba_hogar.models import EstadoCordobaHogar, LocalidadCordobaHogar
from app.cordon_cuneta.models import EstadoCordonCuneta, MunicipioCordonCuneta
from app.mi_lugar.models import EstadoML, ProyectoML

PROGRAMAS: dict[str, tuple[Any, Any]] = {
    "cordon_cuneta": (MunicipioCordonCuneta, EstadoCordonCuneta),
    "cordoba_hogar": (LocalidadCordobaHogar, EstadoCordobaHogar),
    "mi_lugar": (ProyectoML, EstadoML),
}


def _ok_gob(valor: str | None) -> bool | None:
    v = (valor or "").strip().upper()
    if v in ("SI", "SÍ"):
        return True
    if v == "NO":
        return False
    return None


async def lineas(db: AsyncSession, programa: str) -> dict:
    entidad, estado = PROGRAMAS[programa]
    rows = (
        await db.execute(
            select(entidad, estado.label, estado.bg, estado.text_color)
            .outerjoin(estado, estado.id == entidad.estado_general)
            .where(entidad.deleted_at.is_(None))
        )
    ).all()
    salida, sin_id_geo = [], 0
    for e, label, bg, fg in rows:
        if not e.localidad_id:
            sin_id_geo += 1
            continue
        # Sólo CH tiene la firma como dato propio (0046). En CC y ML queda null hasta que el área
        # defina qué dato cuenta como firma (spec §12.3): no se usa `ok_gob` como sustituto.
        firmado = getattr(e, "convenio_firmado", None)
        salida.append({
            "id_geo": e.localidad_id,
            "entidad_id": str(e.id),
            "estado_general": {"label": label, "bg": bg, "text_color": fg} if label else None,
            "ok_gob": _ok_gob(e.ok_gob),
            "convenio_firmado": bool(firmado) if firmado is not None else None,
            "fecha_firma_convenio": (
                e.fecha_firma_convenio.isoformat() if getattr(e, "fecha_firma_convenio", None) else None
            ),
            "monto": float(e.monto) if e.monto is not None else None,
        })
    return {"programa": programa, "lineas": salida, "sin_id_geo": sin_id_geo}
