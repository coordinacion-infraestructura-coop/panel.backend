from pydantic import BaseModel, Field


class CategoriaIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    orden: int = 0
    activo: bool = True
    bg: str | None = None
    text_color: str | None = None


class ProgramaIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    orden: int = 0
    activo: bool = True
    codigo: str | None = Field(default=None, max_length=60)


class AreaIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    orden: int = 0
    activo: bool = True
    es_centinela: bool = False


class CatalogoPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    orden: int | None = None
    activo: bool | None = None
    bg: str | None = None
    text_color: str | None = None
    codigo: str | None = Field(default=None, max_length=60)
    es_centinela: bool | None = None
