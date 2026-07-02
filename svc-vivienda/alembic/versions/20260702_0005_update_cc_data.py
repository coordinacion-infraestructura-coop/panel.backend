"""update_cc_data — sincroniza datos CC con Panel_Cordon_Cuneta (10).html

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-02 00:00:00.000000
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 6 municipios cuyos estados/obs/doc_exp cambiaron en la versión (10) del tablero
    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico = 1781710357683
        WHERE municipio = 'TUCLAME'
    """)

    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico   = 1780942815469,
            etecnico    = 1780942808606,
            efinanciero = 1780942828789,
            obs         = '30/6 PARA NP'
        WHERE municipio = 'CAMILO ALDAO'
    """)

    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico   = 1780942815469,
            etecnico    = 1780942808606,
            efinanciero = 1780942828789,
            obs         = '30/6 PARA NP'
        WHERE municipio = 'COLONIA ITALIANA'
    """)

    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico   = 1780942815469,
            etecnico    = 1780942808606,
            efinanciero = 1780942828789,
            obs         = '30/6 PARA NP'
        WHERE municipio = 'LA PAZ'
    """)

    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico = 4,
            doc_exp   = 'Vuelve el 26/6 para GEOLOCALIZACION - 17/6 TC'
        WHERE municipio = 'LA POBLACIÓN'
    """)

    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico = 4,
            doc_exp   = '29/6 vuelve para GEOLOCALIZACION - 18/6 TC'
        WHERE municipio = 'SAN JAVIER Y YACANTO'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico = 1780942843788
        WHERE municipio = 'TUCLAME'
    """)

    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico   = 3,
            etecnico    = 1780930869659,
            efinanciero = 1,
            obs         = ''
        WHERE municipio = 'CAMILO ALDAO'
    """)

    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico   = 1780930869659,
            etecnico    = 1780930869659,
            efinanciero = 1,
            obs         = '10/4 se NOTIFICA a la Municipalidad'
        WHERE municipio = 'COLONIA ITALIANA'
    """)

    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico   = 1780930869659,
            etecnico    = 1780942780772,
            efinanciero = 1,
            obs         = '10/4 se NOTIFICA a la Municipalidad'
        WHERE municipio = 'LA PAZ'
    """)

    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico = 1781737487934,
            doc_exp   = '17/6 TC'
        WHERE municipio = 'LA POBLACIÓN'
    """)

    op.execute("""
        UPDATE viv_cordon_cuneta
        SET ejuridico = 3,
            doc_exp   = 'Arreglar Exp de GOB y mandar para Convenio'
        WHERE municipio = 'SAN JAVIER Y YACANTO'
    """)
