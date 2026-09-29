from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://user_datos_externos:password@localhost/db_datos_externos"
    gcp_project_id: str = "gestorcooperativo"
    service_name: str = "svc-datos-externos"
    environment: str = "development"

    # Resolución de localidades contra el padrón de svc-vivienda en sync-time
    # (ADR-024, spec-normalizacion-localidades.md §4.5) — mismo patrón que
    # svc-gasifera/svc-gralgob. Vacío -> el resolver devuelve todo sin
    # matchear (id_geo=None) sin bloquear el sync.
    svc_vivienda_internal_url: str = ""
    resolver_localidades_enabled: bool = False

    # ETL de transferencias automáticas a municipios/comunas
    # (spec-resumen-territorial-tablero-v2.md §2.3). El sitio bloquea
    # clientes sin user-agent de navegador — confirmado en el prototipo.
    transferencias_base_url: str = "https://transparencia.cba.gov.ar/transferencias-a-municipios-y-comunas/"
    transferencias_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )


settings = Settings()
