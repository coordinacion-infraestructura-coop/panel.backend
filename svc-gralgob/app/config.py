from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://user_gralgob:password@localhost/db_gralgob"
    gcp_project_id: str = "gestorcooperativo"
    service_name: str = "svc-gralgob"
    environment: str = "development"

    # Sync de solo lectura de la hoja "BD" del Sheet "ATP - Compromiso
    # Gobernador" — ver docs/files/spec-sync-atp-compromiso-gobernador.md.
    # Headers en fila 5 (filas 1-4 son un resumen TOTAL ANUNCIADO/PAGADO/
    # SALDO, no datos). Rango de columnas con margen amplio a propósito: el
    # cronograma mensual (hoy llega a Diciembre 27, columna AT) lo sigue
    # extendiendo el área con el tiempo, y el parseo de esas columnas es
    # genérico por patrón de encabezado (ver app/atp/sync.py), así que no
    # hace falta angostar el rango.
    google_sheet_atp_id: str = ""
    google_sheet_atp_range_bd: str = "BD!A5:EZ5000"
    google_sheet_atp_header_row: int = 5

    # Panel preliminar de solo lectura (spec-sync-atp-compromiso-gobernador.md
    # §12) — auth ADR-015, mismo criterio que svc-privada/svc-gasifera:
    # validación de JWT de Firebase + lookup de portal_usuarios vía endpoint
    # interno IAM-only de svc-vivienda (svc-gralgob NO se conecta a db_vivienda).
    google_jwks_uri: str = (
        "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    )
    google_issuer: str = "https://securetoken.google.com/gestorcooperativo"
    # Vacío -> el lookup degrada a rol "invitado" (dev / gateway sin wiring de IAM).
    svc_vivienda_internal_url: str = ""

    # Notificación al panel de svc-vivienda (ADR-019/ADR-023) cuando el sync detecta
    # un compromiso NUEVO. Flag independiente (mismo criterio que
    # privada_sync_gestiones_enabled/ADR-020) para poder activar/desactivar sin tocar
    # svc_vivienda_internal_url (que ya se usa para el auth lookup, ADR-015).
    notificar_fila_nueva_enabled: bool = False


settings = Settings()
