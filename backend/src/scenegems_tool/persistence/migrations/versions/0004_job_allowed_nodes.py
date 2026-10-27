"""The nodes a job may run on.

New column: job.allowed_nodes, a JSON array of node ids that may claim the job (a campaign's
selected nodes); empty means any node. Jobs submitted before this revision get an empty one.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job", sa.Column("allowed_nodes", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade() -> None:
    op.drop_column("job", "allowed_nodes")
