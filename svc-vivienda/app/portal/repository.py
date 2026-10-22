from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.portal.models import PortalUsuario, PortalUsuarioArea, PortalUsuarioSecretaria

_CON_RELACIONES = (selectinload(PortalUsuario.secretarias), selectinload(PortalUsuario.areas))


async def get_portal_user(db: AsyncSession, email: str) -> PortalUsuario | None:
    result = await db.execute(
        select(PortalUsuario)
        .options(*_CON_RELACIONES)
        .where(PortalUsuario.email == email.lower())
        .where(PortalUsuario.activo.is_(True))
    )
    return result.scalar_one_or_none()


async def get_portal_user_any_status(db: AsyncSession, email: str) -> PortalUsuario | None:
    result = await db.execute(
        select(PortalUsuario)
        .options(*_CON_RELACIONES)
        .where(PortalUsuario.email == email.lower())
    )
    return result.scalar_one_or_none()


async def list_usuarios(db: AsyncSession) -> list[PortalUsuario]:
    result = await db.execute(
        select(PortalUsuario)
        .options(*_CON_RELACIONES)
        .order_by(PortalUsuario.email)
    )
    return list(result.scalars().all())


async def create_usuario(
    db: AsyncSession,
    email: str,
    nombre: str | None,
    rol: str,
    secretarias: list[str],
    actor_email: str,
    areas: list[dict] | None = None,
) -> PortalUsuario:
    usuario = PortalUsuario(
        email=email.lower(),
        nombre=nombre,
        rol=rol,
        activo=True,
        created_by=actor_email,
        updated_by=actor_email,
    )
    db.add(usuario)
    await db.flush()

    for sec in secretarias:
        db.add(PortalUsuarioSecretaria(email=usuario.email, secretaria=sec))
    for a in areas or []:
        db.add(PortalUsuarioArea(email=usuario.email, **a))

    await db.flush()
    result = await db.execute(
        select(PortalUsuario)
        .options(*_CON_RELACIONES)
        .where(PortalUsuario.email == usuario.email)
    )
    return result.scalar_one()


async def update_usuario(
    db: AsyncSession,
    email: str,
    updates: dict,
    actor_email: str,
) -> PortalUsuario | None:
    result = await db.execute(
        select(PortalUsuario)
        .options(*_CON_RELACIONES)
        .where(PortalUsuario.email == email.lower())
    )
    usuario = result.scalar_one_or_none()
    if not usuario:
        return None

    if "nombre" in updates:
        usuario.nombre = updates["nombre"]
    if "rol" in updates:
        usuario.rol = updates["rol"]
    if "activo" in updates:
        usuario.activo = updates["activo"]
    if "secretarias" in updates:
        await db.execute(
            delete(PortalUsuarioSecretaria).where(
                PortalUsuarioSecretaria.email == usuario.email
            )
        )
        for sec in updates["secretarias"]:
            db.add(PortalUsuarioSecretaria(email=usuario.email, secretaria=sec))
        if "areas" not in updates:
            # Las áreas de una secretaría quitada se van con ella.
            await db.execute(
                delete(PortalUsuarioArea).where(
                    PortalUsuarioArea.email == usuario.email,
                    PortalUsuarioArea.secretaria.not_in(updates["secretarias"]),
                )
            )
    if "areas" in updates:
        await db.execute(delete(PortalUsuarioArea).where(PortalUsuarioArea.email == usuario.email))
        for a in updates["areas"]:
            db.add(PortalUsuarioArea(email=usuario.email, **a))

    usuario.updated_by = actor_email
    await db.flush()
    # Expira la relación cacheada en el identity map para que el siguiente acceso
    # la recargue desde DB (el bulk DELETE no invalida automáticamente el cache ORM).
    await db.refresh(usuario, attribute_names=["secretarias", "areas"])
    return usuario


async def delete_usuario(db: AsyncSession, email: str) -> bool:
    result = await db.execute(
        select(PortalUsuario).where(PortalUsuario.email == email.lower())
    )
    usuario = result.scalar_one_or_none()
    if not usuario:
        return False
    await db.delete(usuario)
    await db.flush()
    return True
