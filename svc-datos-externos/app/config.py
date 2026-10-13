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

    # Sync de solo lectura del nomenclador de localidades de Gobierno y de la
    # ficha de localidad (spec-datos-externos-fase1-nomenclador-demografia.md
    # §5). Defaults vacíos/apagados; los valores reales viven en
    # services/cloudbuild.yaml (un `gcloud run deploy --set-env-vars` pisa
    # todo el set de variables).
    google_sheet_gob_nomenclador_id: str = ""
    google_sheet_gob_resumen_general_id: str = ""
    gob_localidades_sync_enabled: bool = False


settings = Settings()
