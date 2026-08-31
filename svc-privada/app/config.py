from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://user_privada:devpassword@localhost:5433/db_privada"
    gcp_project_id: str = "gestorcooperativo"
    service_name: str = "svc-privada"
    environment: str = "development"

    # Validación del JWT de Firebase (mismo criterio que svc-vivienda).
    google_jwks_uri: str = (
        "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    )
    google_issuer: str = "https://securetoken.google.com/gestorcooperativo"

    # ADR-015 — Auth unificada en portal_usuarios (que vive en db_vivienda).
    # svc-privada NO se conecta a db_vivienda: consulta un endpoint interno IAM-only
    # de svc-vivienda. Vacío -> el lookup degrada a rol "invitado" (dev / gateway sin wiring).
    svc_vivienda_internal_url: str = ""


settings = Settings()
