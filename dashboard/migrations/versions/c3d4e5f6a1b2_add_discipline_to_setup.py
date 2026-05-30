"""Add discipline column to setup

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-05-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a1b2'
down_revision = 'b2c3d4e5f6a1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('setup', schema=None) as batch_op:
        batch_op.add_column(sa.Column('discipline', sa.String(),
                                      nullable=True, server_default='enduro'))


def downgrade():
    with op.batch_alter_table('setup', schema=None) as batch_op:
        batch_op.drop_column('discipline')
