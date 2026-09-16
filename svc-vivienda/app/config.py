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

    # Resumen Territorial — federación server-side de svc-privada (ADR-016 / E5a).
    # `privada_fetch_enabled=True` + `svc_privada_internal_url` seteada → el job de
    # cómputo llama al endpoint IAM-only de svc-privada (`/internal/privada/rollup-territorial`)
    # con un ID token cuyo audience es esa misma URL de Cloud Run. Requiere que la SA
    # `svc-vivienda@` tenga `roles/run.invoker` sobre svc-privada.
    # Si `svc_privada_internal_url` está vacía, cae al camino viejo (gateway + audience
    # de proyecto), que svc-privada rechaza — dejar así desactiva la federación server-side.
    privada_fetch_enabled: bool = False
    svc_privada_internal_url: str = ""
    privada_rollup_internal_path: str = "/internal/privada/rollup-territorial"
    gateway_base_url: str = "https://ministerio-gateway-3j5k00ma.uc.gateway.dev"
    privada_resumen_path: str = "/api/v1/privada/gestiones/resumen-territorial"
    privada_gateway_audience: str = ""  # vacío → gcp_project_id como aud del ID token

    # Vinculación Vivienda -> Privada (ADR-020 / spec-vinculacion-vivienda-privada.md).
    # Flag independiente de `privada_fetch_enabled` (que es sólo para el fetch de
    # resumen_territorial) — permite prender/apagar el sync de gestiones por separado.
    # Reusa `svc_privada_internal_url` de arriba como base + audience del ID token.
    privada_sync_gestiones_enabled: bool = False
    privada_gestiones_sync_internal_path: str = "/internal/privada/gestiones/sync"

    # Informe "Localidades por Departamento" (spec-informe-localidades-departamento.md).
    # Reusa `privada_fetch_enabled` + `svc_privada_internal_url` de arriba — mismo
    # flag/URL, sólo agrega el path del endpoint IAM-only de habitantes.
    privada_localidades_internal_path: str = "/internal/privada/localidades-habitantes"


settings = Settings()
