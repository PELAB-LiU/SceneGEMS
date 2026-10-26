"""The machine a node runs on.

New column: node.machine, the name of the machine as the deployment tool knows it (the node
reports it in its Hello). Nodes registered before this revision have none until they say
hello again.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("node", sa.Column("machine", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("node", "machine")
