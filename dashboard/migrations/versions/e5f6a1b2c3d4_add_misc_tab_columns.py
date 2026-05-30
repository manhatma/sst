"""Add Misc-tab columns to session_html

Revision ID: e5f6a1b2c3d4
Revises: d4e5f6a1b2c3
Create Date: 2026-05-30 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a1b2c3d4'
down_revision = 'd4e5f6a1b2c3'
branch_labels = None
depends_on = None

_COLUMNS = ['pv_front', 'pv_rear', 'pv_comp',
            'accel_front', 'accel_rear', 'fr_scatter']


def upgrade():
    with op.batch_alter_table('session_html', schema=None) as batch_op:
        for col in _COLUMNS:
            batch_op.add_column(sa.Column(col, sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table('session_html', schema=None) as batch_op:
        for col in reversed(_COLUMNS):
            batch_op.drop_column(col)
