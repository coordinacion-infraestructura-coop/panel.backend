import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthUser


async def log_audit(
    db: AsyncSession,
    *,
    actor: AuthUser,
    action: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """
    Registra una acción de escritura en el log de auditoría.
    Implementación en tabla dedicada viv_audit_log (definida en migración).
    """
    from sqlalchemy import text
    await db.execute(
        text("""
            INSERT INTO viv_audit_log
                (id, actor_uid, actor_email, actor_role, action,
                 resource_type, resource_id, payload, created_at)
            VALUES
                (:id, :uid, :email, :role, :action,
                 :resource_type, :resource_id, CAST(:payload AS jsonb), :created_at)
        """),
        {
            "id": str(uuid.uuid4()),
            "uid": actor.uid,
            "email": actor.email,
            "role": actor.role,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "payload": json.dumps(payload or {}, default=str),
            "created_at": datetime.now(timezone.utc),
        },
    )
