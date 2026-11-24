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

    # ADR-024 — resolución de (departamento, localidad) contra el padrón
    # canónico de svc-vivienda (viv_geo_localidades), aplicada al rollup
    # territorial (no persiste id_geo por gestión, sólo en el agregado que
    # consume resumen_territorial). Mismo criterio que Gasífera/Gralgob.
    resolver_localidades_enabled: bool = False

    # ADR-027 — padrón político único (spec-padron-politico-gobierno-privada.md): el
    # intendente y el partido salen de Gobierno vía el endpoint IAM-only de
    # svc-datos-externos. Apagado por defecto; services/cloudbuild.yaml lo enciende.
    svc_datos_externos_internal_url: str = ""
    padron_politico_sync_enabled: bool = False

    # ADR-036 — planificación de programas: cruces de solo lectura por IAM con los paneles de
    # cada programa y con datos externos (spec-privada-planificacion-programas.md §6). Apagado
    # por defecto (local/tests); services/cloudbuild.yaml lo enciende junto con las URLs.
    planificacion_fetch_enabled: bool = False
    svc_gasifera_internal_url: str = ""
    svc_gralgob_internal_url: str = ""

    # Inscriptos al Congreso de Formación Digital 2026 -> Planificación
    # (spec-privada-sync-capacitacion.md §7). El id de la planilla no es secreto: va como default
    # para que un redeploy de CI (`--set-env-vars` reemplaza todo) no lo borre. Vacío = apagado.
    capacitacion_sheet_id: str = "1bvY7X7_jbzMf8XXajJmwsjY1s0dRP4TBdJqsQ2H1t5w"
    capacitacion_rango_respuestas: str = "'Respuestas de formulario 1'!A:F"
    capacitacion_rango_lista: str = "Lista!A:B"


settings = Settings()
