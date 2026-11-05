from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    service_name: str = "svc-agente"
    environment: str = "development"
    gcp_project_id: str = "gestorcooperativo"

    # db_agente — tablas propias del servicio (conversaciones, auditoría) y schema `ag`
    # (capa semántica). Rol `agente_app` (spec §2.3).
    database_url: str = "postgresql+asyncpg://agente_app:devpassword@localhost:5437/db_agente"
    # Mismo db_agente, rol `agente_llm`: SELECT sólo sobre `ag.*`, solo lectura.
    # Vacío -> se usa database_url (dev/tests). En producción DEBE estar configurado:
    # la garantía de solo lectura de `consulta_sql` es el rol, no el validador.
    llm_database_url: str = ""

    # Fuentes del refresco (spec §2.2, plan B ETL). Rol `agente_ro` con SELECT por columna.
    # Las cinco bases están en la misma instancia y con el mismo rol: alcanza una plantilla con
    # `{db}` (un solo secreto). Una URL específica, si está, gana sobre la plantilla.
    # Todo vacío -> la fuente se saltea y queda "sin configurar" en ag_frescura.
    fuentes_url_plantilla: str = ""
    fuente_vivienda_url: str = ""
    fuente_privada_url: str = ""
    fuente_gasifera_url: str = ""
    fuente_gralgob_url: str = ""
    fuente_datos_externos_url: str = ""

    # Auth (ADR-015): JWT Firebase + lookup IAM a svc-vivienda.
    google_jwks_uri: str = (
        "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    )
    google_issuer: str = "https://securetoken.google.com/gestorcooperativo"
    svc_vivienda_internal_url: str = ""

    # LLM — Claude vía Vertex AI (spec §6.1). Sin API keys: ADC de la SA de Cloud Run.
    vertex_region: str = "global"
    vertex_project_id: str = "gestorcooperativo"
    modelo: str = "claude-sonnet-5-5"
    esfuerzo: str = "medium"
    max_rondas_tools: int = 6
    max_tokens: int = 16000

    # Costo estimado por pregunta en ag_interacciones (USD por millón de tokens). Valores de
    # referencia de la API de Anthropic para Sonnet; Vertex factura aparte con su propia tarifa.
    precio_entrada_mtok: float = 2.0
    precio_salida_mtok: float = 10.0
    precio_cache_lectura_mtok: float = 0.2
    precio_cache_escritura_mtok: float = 2.5

    # Límites (spec §6.2 / §6.4)
    sql_limite_filas: int = 500
    sql_timeout_ms: int = 10000
    cuota_diaria: int = 100

    # Base de los links del portal (spec §5.2)
    portal_url: str = "https://gestorcooperativo.web.app"


settings = Settings()
