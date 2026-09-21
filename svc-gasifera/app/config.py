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


settings = Settings()
