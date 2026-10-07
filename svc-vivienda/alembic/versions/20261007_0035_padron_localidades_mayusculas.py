"""Padrón oficial: nombres de localidad en mayúsculas (grafía única)

El padrón `viv_geo_localidades` es la fuente oficial del nombre de cada
localidad — de ahí lo toma `resumen_territorial` (por `id_geo`, ADR-024) y los
desplegables de Cordón Cuneta / Córdoba Hogar / Mi Lugar. Pero su grafía no era
pareja: de 544 filas, 30 estaban cargadas enteras en minúsculas ("Villa de
Pocho", casi todas las altas posteriores, id 533–560) y otras 24 traían el
alias entre paréntesis en minúsculas, varias con una "O"/"I" mayúscula en lugar
de la vocal acentuada ("CHARRAS (Villa ColOn)", "LA CAROLINA (El PotosI)").
Reportado por el usuario 2026-10-07: al filtrar el Resumen Territorial por
departamento Pocho aparecían localidades en minúsculas mezcladas con el resto.

Se pasa `localidad` a mayúsculas en todas las filas donde no lo está — misma
convención que el resto del padrón. No cambia ningún `id_geo` ni ningún
matching: todo el matching contra el padrón normaliza tildes y mayúsculas
(`app/geo/matching.py`), y nadie compara este texto por igualdad exacta.

La conversión se hace en Python y no con `UPPER()` de SQL a propósito: según
la collation de la base, `UPPER()` puede dejar sin convertir las letras
acentuadas y la "ñ".

No toca el texto libre de `viv_cordon_cuneta` / `viv_cordoba_hogar` /
`viv_ml_proyectos` (spec-normalizacion-localidades.md §2.6: ese campo no se
pisa; lo que los ata al padrón es `localidad_id`).

Después de aplicar: recalcular el snapshot de `resumen_territorial` (botón
"Actualizar" o la tarea programada) para que tome los nombres nuevos.

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

# Grafía previa de las 54 filas conocidas (docs/data/geo_localidades.json), para
# poder volver atrás. Filas que no estén acá no se restauran en el downgrade.
_GRAFIA_PREVIA = {
    "560": "Villa Ciudad Parque los Reartes",
    "541": "Alto de los Quebrachos",
    "536": "Bañado de Soto",
    "535": "Cruz de Caña",
    "540": "Guanaco Muerto",
    "537": "La Batea",
    "533": "La Higuera",
    "534": "Las Cañadas",
    "538": "Las Playas",
    "539": "Los Chañaritos",
    "542": "Media Naranja",
    "551": "Cañada de Río Pinto",
    "553": "Chuña",
    "552": "Copacabana",
    "554": "Olivares de San Nicolás",
    "105": "CASTRO URDIALES - Colonia 25 de Mayo",
    "545": "Estancia de Guadalupe",
    "544": "Guasapampa",
    "543": "Talaini",
    "546": "Tosno",
    "550": "Las Palmas",
    "547": "Los Talares",
    "548": "San Gerónimo",
    "549": "Villa de Pocho",
    "555": "Charbonier",
    "558": "Eufrasio Loza",
    "241": "Agua de Oro",
    "556": "Chuña Huasi",
    "557": "Pozo Nuevo",
    "559": "Rosario del Saladillo",
    "386": "CERRO DE SAN LORENZO (Salto de Toledo)",
    "387": "SOCONCHO (las Bajadas)",
    "43": "HIGUERAS (la Higuera)",
    "405": "LOS SAUCES (San Marcos)",
    "48": "VILLA DE SOTO (Est. Soto)",
    "53": "SANTA MAGDALENA (Est. Jovita)",
    "78": "CAÑADA DE RIO PINTO (la Verde)",
    "84": "ALEJANDRO ROCA (Est. Alejandro)",
    "88": "CHARRAS (Villa ColOn)",
    "433": "OLMOS (Villa Felipa)",
    "98": "SANTA EUFEMIA (Pueblo Pelleschi)",
    "103": "CAP. GRAL. B.OHIGGINS (Colonia Progreso)",
    "437": "COLONIA VEINTICINCO (RIo III)",
    "428": "LOS PAREDONES (Santa Isabel)",
    "213": "SAN PEDRO (Gutemberg)",
    "170": "LA CAROLINA (El PotosI)",
    "185": "VICUÑA MACKENNA (Est. Torres)",
    "463": "TALA NORTE (El Alcalde)",
    "285": "LA TORDILLA (Colonia la Tordilla)",
    "297": "SEEBER (Est. Seeber)",
    "304": "DESPEÑADEROS (EstaciOn Lucas A. de Olmos)",
    "502": "EL TALITA (Villa Gutierrez)",
    "343": "SARMIENTO (Gral. Alvear)",
    "371": "MONTE LEÑA (General Bustos)",
}


def upgrade() -> None:
    conn = op.get_bind()
    filas = conn.execute(sa.text("SELECT id_geo, localidad FROM viv_geo_localidades")).fetchall()
    for id_geo, localidad in filas:
        nueva = localidad.upper()
        if nueva != localidad:
            conn.execute(
                sa.text("UPDATE viv_geo_localidades SET localidad = :localidad WHERE id_geo = :id_geo"),
                {"localidad": nueva, "id_geo": id_geo},
            )


def downgrade() -> None:
    conn = op.get_bind()
    for id_geo, localidad in _GRAFIA_PREVIA.items():
        # Sólo si la fila sigue con la grafía que dejó el upgrade — no pisa una
        # corrección manual posterior.
        conn.execute(
            sa.text(
                "UPDATE viv_geo_localidades SET localidad = :localidad "
                "WHERE id_geo = :id_geo AND localidad = :actual"
            ),
            {"localidad": localidad, "id_geo": id_geo, "actual": localidad.upper()},
        )
