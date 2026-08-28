from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://user_vivienda:password@localhost/db_vivienda"
    gcp_project_id: str = "gestorcooperativo"
    service_name: str = "svc-vivienda"
    environment: str = "development"
    pubsub_topic_vivienda: str = "ministerio-eventos-vivienda"
    google_jwks_uri: str = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    google_issuer: str = "https://securetoken.google.com/gestorcooperativo"

    # Sync del checklist técnico de Cordón Cuneta (Google Sheet "Base TOTAL")
    google_sheet_cc_id: str = ""
    google_sheet_cc_range: str = "Base TOTAL!A6:AR400"

    # Resumen Territorial — llamada servidor-a-servidor a svc-privada vía API Gateway (spec §3.3)
    gateway_base_url: str = "https://ministerio-gateway-3j5k00ma.uc.gateway.dev"
    privada_resumen_path: str = "/api/v1/privada/gestiones/resumen-territorial"
    # El securityDefinition `google_accounts` del gateway exige aud="gestorcooperativo"
    # (x-google-audiences). Vacío → se usa gcp_project_id como audience del ID token.
    privada_gateway_audience: str = ""


settings = Settings()
