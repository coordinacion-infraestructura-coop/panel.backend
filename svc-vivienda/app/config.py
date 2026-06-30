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


settings = Settings()
