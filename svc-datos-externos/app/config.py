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

    # ATP Interno para el Resumen general del tablero (spec-atp-interno.md §4.2): endpoint
    # IAM-only de svc-gralgob. Apagado por defecto; services/cloudbuild.yaml lo enciende.
    svc_gralgob_internal_url: str = ""
    atp_interno_fetch_enabled: bool = False

    # Auth de los paneles (ADR-028): JWT de Firebase validado contra las claves
    # públicas de Google; el rol sale de svc-vivienda por la URL de arriba (ADR-015).
    google_jwks_uri: str = (
        "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    )
    google_issuer: str = "https://securetoken.google.com/gestorcooperativo"

    # ETL de transferencias automáticas a municipios/comunas
    # (spec-resumen-territorial-tablero-v2.md §2.3). El sitio bloquea
    # clientes sin user-agent de navegador — confirmado en el prototipo.
    transferencias_base_url: str = "https://transparencia.cba.gov.ar/transferencias-a-municipios-y-comunas/"
    transferencias_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )

    # Sync de solo lectura del nomenclador de localidades de Gobierno y de la
    # vista por localidad "0. Resumen General - Vista" (spec-datos-externos-fase1-nomenclador-demografia.md
    # §5). Defaults vacíos/apagados; los valores reales viven en
    # services/cloudbuild.yaml (un `gcloud run deploy --set-env-vars` pisa
    # todo el set de variables).
    google_sheet_gob_nomenclador_id: str = ""
    google_sheet_gob_resumen_vista_id: str = ""
    gob_localidades_sync_enabled: bool = False

    # Planillas de transferencias de Gobierno (spec-datos-externos-fase2-transferencias.md §3):
    # COPA, FOFINDES, FODEMEP, FOMMEP y EMPLEADOS. Mismo criterio: valores reales en
    # services/cloudbuild.yaml, compartidas como Lector con svc-datos-externos@.
    google_sheet_gob_copa_id: str = ""
    google_sheet_gob_fofindes_id: str = ""
    google_sheet_gob_fodemep_id: str = ""
    google_sheet_gob_fommep_id: str = ""
    google_sheet_gob_empleados_id: str = ""
    # Fase 3 (spec-datos-externos-fase3-fondos.md §3): mismas reglas, mismo sync y mismo flag.
    google_sheet_gob_fondo_permanente_id: str = ""
    google_sheet_gob_fondo_ambiental_id: str = ""
    google_sheet_gob_comunidades_regionales_id: str = ""
    gob_transferencias_sync_enabled: bool = False

    # WFS público de IDECOR (Catastro) para la valuación de parcelas de Mi Lugar
    # (spec-mi-lugar-valor-fiscal-idecor.md §4, ADR-031). Sin autenticación.
    idecor_wfs_url: str = "https://idecor-ws.mapascordoba.gob.ar/geoserver/idecor/wfs"
    idecor_timeout_segundos: float = 30

    # Fuentes oficiales públicas por gobierno local
    # (spec-datos-externos-fuentes-oficiales.md §2). Los nombres de capa van
    # en configuración porque Estadística los publica con fecha
    # (`IPS_23102025`): si cambian, se corrigen sin tocar código.
    fuentes_oficiales_sync_enabled: bool = False
    fuentes_oficiales_timeout_segundos: float = 120
    estadistica_arcgis_base: str = "https://smart-geo-data.cba.gov.ar/server/rest/services"
    est_capa_ficha: str = "Estadistica_Censos/Conoce_cordoba_Municipio_FichaGral_VP/FeatureServer/0"
    est_capa_condvida: str = "Estadistica_Censos/MUN_CondVida_VP/FeatureServer/0"
    est_capa_pobviv: str = "Sitio_Web_Estadistica/PobTotalViv_VP/FeatureServer/0"
    est_capa_educacion: str = "Estadistica_Censos/MUN_Educacion_VP/FeatureServer/0"
    est_capa_salud: str = "Estadistica_Censos/MUN_Salud_VP/FeatureServer/0"
    est_capa_laboral: str = "Estadistica_Censos/MUN_MercadoLaboral_VP/FeatureServer/0"
    est_capa_ips: str = "IPS/IPS_23102025/FeatureServer/0"
    est_capa_departamentos: str = "Estadistica_Censos/Dpto_2022_VP/FeatureServer/0"
    est_capa_poligonos: str = "Estadistica_Censos/MyC_2022_VP/FeatureServer/0"
    # RENABAP 2023 desde el servidor de datos de Poblaciones (endpoint no
    # documentado; dataset 383501 de la obra 191801).
    renabap_csv_url: str = (
        "https://datos-poblaciones.conicet.gov.ar/services/download/GetDatasetFile?t=c&d=383501&w=191801"
    )
    renabap_version: str = "2023"


settings = Settings()
