"""Add balance_metrics column to session_html

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-05-30 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a1b2c3'
down_revision = 'c3d4e5f6a1b2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('session_html', schema=None) as batch_op:
        batch_op.add_column(sa.Column('balance_metrics', sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table('session_html', schema=None) as batch_op:
        batch_op.drop_column('balance_metrics')
