from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://user_gasifera:password@localhost/db_gasifera"
    gcp_project_id: str = "gestorcooperativo"
    service_name: str = "svc-gasifera"
    environment: str = "development"

    # Sync de solo lectura del Sheet "SEC. GAS PIT" — ver
    # docs/files/spec-sync-gasifera-pit.md
    google_sheet_gas_pit_id: str = ""
    google_sheet_gas_pit_range_matriz: str = "MATRIZ (NO TOMAR)!A1:AC500"
    google_sheet_gas_pit_range_acciones: str = "ACCIONES TERRITORIO!A1:O1100"
    # Tipo de cambio USD usado para recalcular monto_inversion_usd en
    # gas_pit_acciones_territorio (ver spec §5.3 — no se lee de la hoja
    # "monto actualizado ", acoplada por posición de fila).
    tipo_cambio_usd: float = 1460.0

    # Panel preliminar de solo lectura (spec-sync-gasifera-pit.md §12) — auth
    # ADR-015, mismo criterio que svc-privada: validación de JWT de Firebase +
    # lookup de portal_usuarios vía endpoint interno IAM-only de svc-vivienda
    # (svc-gasifera NO se conecta a db_vivienda).
    google_jwks_uri: str = (
        "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    )
    google_issuer: str = "https://securetoken.google.com/gestorcooperativo"
    # Vacío -> el lookup degrada a rol "invitado" (dev / gateway sin wiring de IAM).
    svc_vivienda_internal_url: str = ""

    # Notificación al panel de svc-vivienda (ADR-019/ADR-023) cuando el sync detecta
    # una acción territorial NUEVA. Flag independiente (mismo criterio que
    # privada_sync_gestiones_enabled/ADR-020) para poder activar/desactivar sin tocar
    # svc_vivienda_internal_url (que ya se usa para el auth lookup, ADR-015).
    notificar_fila_nueva_enabled: bool = False


settings = Settings()
