"""Catálogos editables en runtime (spec-privada-categorias-programas.md / ADR-010).

Tres catálogos independientes — NO hay mapa relacional obligatorio Categoría→Programa→Área
(D-1). El alta/edición de una gestión elige libremente de cada desplegable.

Patrón `viv_cc_estados` de svc-vivienda: `id` BigInteger PK client-generated
(`int(time.time()*1000)`), `label`, `orden`, `activo`, colores opcionales. CRUD desde un
panel de administración (`ROLES_TRANSICION`); `DELETE` con guard 409 si está en uso.

`priv_categorias` supersede el catálogo legacy `priv_cat_categoria_general` (que se conserva
durante la ventana de compatibilidad del informe — E4).
"""
from sqlalchemy import BigInteger, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class _CatEditableBase(Base):
    __abstract__ = True

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # `default` (Python-side) además de `server_default`: en SQLite el server_default
    # "true" se guarda como string y rompe los filtros `activo.is_(True)`.
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class Categoria(_CatEditableBase):
    __tablename__ = "priv_categorias"
    # colores para el chip en la UI (opcionales — hex "#rrggbb")
    bg: Mapped[str | None] = mapped_column(String(10))
    text_color: Mapped[str | None] = mapped_column(String(10))


class Programa(_CatEditableBase):
    __tablename__ = "priv_programas"
    # código normalizado, único — para correlación string-keyed con programas de otras áreas
    codigo: Mapped[str | None] = mapped_column(String(60), unique=True)


class Area(_CatEditableBase):
    __tablename__ = "priv_areas"
    # nodo centinela "Área desconocida" para el backfill del DAG (E3)
    es_centinela: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
