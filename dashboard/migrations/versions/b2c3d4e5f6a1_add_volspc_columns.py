"""Add front_volspc and rear_volspc columns to session

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-03-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a1'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('session', schema=None) as batch_op:
        batch_op.add_column(sa.Column('front_volspc', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('rear_volspc', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('session', schema=None) as batch_op:
        batch_op.drop_column('rear_volspc')
        batch_op.drop_column('front_volspc')
