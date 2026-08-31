"""Catálogos legacy migrados 1:1 desde BigQuery `infra_gestion.cat_*`.

Forma común: id VARCHAR PK, nombre, orden INT, activo BOOL, descripcion.
`priv_cat_categoria_general` es el catálogo LEGACY de clasificación; el spec hijo
`spec-privada-categorias-programas.md` introduce `priv_categorias` (editable en runtime)
que lo supersede — esas tablas NO se crean en esta migración.
"""
from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class _CatalogoBase(Base):
    __abstract__ = True

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    orden: Mapped[int | None] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    descripcion: Mapped[str | None] = mapped_column(Text)


class CatEstado(_CatalogoBase):
    __tablename__ = "priv_cat_estado"


class CatUrgencia(_CatalogoBase):
    __tablename__ = "priv_cat_urgencia"


class CatMinisterioAgencia(_CatalogoBase):
    __tablename__ = "priv_cat_ministerio_agencia"


class CatCategoriaGeneral(_CatalogoBase):
    __tablename__ = "priv_cat_categoria_general"


class CatTipoGestion(_CatalogoBase):
    __tablename__ = "priv_cat_tipo_gestion"


class CatCanalOrigen(_CatalogoBase):
    __tablename__ = "priv_cat_canal_origen"
