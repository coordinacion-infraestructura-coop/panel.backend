from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, func
from sqlalchemy.orm import relationship

from app.database import Base


class PortalUsuario(Base):
    __tablename__ = "portal_usuarios"

    email = Column(String(255), primary_key=True)
    nombre = Column(String(255))
    rol = Column(String(50), nullable=False, default="Operador")
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(String(255))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    updated_by = Column(String(255))

    secretarias = relationship(
        "PortalUsuarioSecretaria",
        back_populates="usuario",
        cascade="all, delete-orphan",
    )


class PortalUsuarioSecretaria(Base):
    __tablename__ = "portal_usuario_secretarias"

    email = Column(
        String(255),
        ForeignKey("portal_usuarios.email", ondelete="CASCADE"),
        primary_key=True,
    )
    secretaria = Column(String(100), primary_key=True)

    usuario = relationship("PortalUsuario", back_populates="secretarias")
