"""add_sentiment_columns

Revision ID: 1bed0b2a3964
Revises: b33b18452387
Create Date: 2026-01-07 22:01:33.626890

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1bed0b2a3964'
down_revision: Union[str, Sequence[str], None] = 'b33b18452387'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('responses', sa.Column('response_text', sa.Text(), nullable=True))
    op.add_column('responses', sa.Column('sentiment_score', sa.Float(), nullable=True))
    
    with op.batch_alter_table('question_bank') as batch_op:
        batch_op.add_column(sa.Column('response_type', sa.String(), server_default='scale', nullable=False))


def downgrade():
    with op.batch_alter_table('responses') as batch_op:
        batch_op.drop_column('sentiment_score')
        batch_op.drop_column('response_text')
        
    with op.batch_alter_table('question_bank') as batch_op:
        batch_op.drop_column('response_type')
