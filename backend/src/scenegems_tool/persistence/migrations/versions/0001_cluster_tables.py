"""Cluster tables: node, node_capability, node_fingerprint, job, job_event.

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum values as of this revision; a later revision that adds a value replaces the constraint.
NODE_STATUSES = ("online", "draining", "offline")
JOB_TYPES = ("scene_generation", "trajectory_generation", "simulation.kinematic", "simulation.ardupilot", "monitoring.post_hoc")
JOB_STATES = ("queued", "leased", "running", "succeeded", "failed", "cancelled")
JOB_EVENT_KINDS = ("submitted", "leased", "accepted", "rejected", "released", "expired", "attempt_failed", "succeeded", "failed", "cancelled")


def _one_of(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _timestamp() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "node",
        sa.Column("id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=False),
        sa.Column("software_revision", sa.String(64), nullable=False),
        sa.Column("cpus", sa.Float(), nullable=False),
        sa.Column("memory_mb", sa.Integer(), nullable=False),
        sa.Column("free_memory_mb", sa.Integer(), nullable=False),
        sa.Column("free_disk_mb", sa.Integer(), nullable=False),
        sa.Column("load_average", sa.Float(), nullable=False),
        sa.Column("registered_at", _timestamp(), nullable=False),
        sa.Column("last_seen_at", _timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_node"),
        sa.CheckConstraint(_one_of("status", NODE_STATUSES), name="ck_node_status"),
    )
    op.create_index("ix_node_last_seen_at", "node", ["last_seen_at"])

    op.create_table(
        "node_capability",
        sa.Column("node_id", sa.String(128), nullable=False),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("slots", sa.Integer(), nullable=False),
        sa.Column("slots_in_use", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("node_id", "job_type", name="pk_node_capability"),
        sa.ForeignKeyConstraint(["node_id"], ["node.id"], name="fk_node_capability_node_id_node", ondelete="CASCADE"),
        sa.CheckConstraint(_one_of("job_type", JOB_TYPES), name="ck_node_capability_job_type"),
        sa.CheckConstraint("slots >= 1", name="ck_node_capability_slots_positive"),
        sa.CheckConstraint("slots_in_use >= 0", name="ck_node_capability_slots_in_use_not_negative"),
    )

    op.create_table(
        "node_fingerprint",
        sa.Column("node_id", sa.String(128), nullable=False),
        sa.Column("image", sa.String(256), nullable=False),
        sa.Column("fingerprint", sa.String(256), nullable=False),
        sa.PrimaryKeyConstraint("node_id", "image", name="pk_node_fingerprint"),
        sa.ForeignKeyConstraint(["node_id"], ["node.id"], name="fk_node_fingerprint_node_id_node", ondelete="CASCADE"),
    )

    op.create_table(
        "job",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("required_labels", postgresql.JSONB(), nullable=False),
        sa.Column("required_fingerprints", postgresql.JSONB(), nullable=False),
        sa.Column("min_memory_mb", sa.Integer(), nullable=False),
        sa.Column("min_cpus", sa.Float(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_id", sa.String(36), nullable=True),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", _timestamp(), nullable=True),
        sa.Column("submitted_at", _timestamp(), nullable=False),
        sa.Column("updated_at", _timestamp(), nullable=False),
        sa.Column("started_at", _timestamp(), nullable=True),
        sa.Column("finished_at", _timestamp(), nullable=True),
        sa.Column("result_attempt", sa.Integer(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_job"),
        sa.UniqueConstraint("seq", name="uq_job_seq"),
        sa.UniqueConstraint("idempotency_key", name="uq_job_idempotency_key"),
        sa.UniqueConstraint("lease_id", name="uq_job_lease_id"),
        sa.ForeignKeyConstraint(["lease_owner"], ["node.id"], name="fk_job_lease_owner_node"),
        sa.CheckConstraint(_one_of("job_type", JOB_TYPES), name="ck_job_job_type"),
        sa.CheckConstraint(_one_of("state", JOB_STATES), name="ck_job_state"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_job_max_attempts_positive"),
        sa.CheckConstraint("attempt >= 0", name="ck_job_attempt_not_negative"),
        sa.CheckConstraint("failed_attempts >= 0 AND failed_attempts <= attempt", name="ck_job_failed_attempts_within_attempts"),
        sa.CheckConstraint(
            "state NOT IN ('leased', 'running') OR (lease_id IS NOT NULL AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_job_active_lease_complete",
        ),
    )
    op.create_index("ix_job_queue_order", "job", [sa.text("priority DESC"), "submitted_at", "seq"], postgresql_where=sa.text("state = 'queued'"))
    op.create_index("ix_job_active_lease_expiry", "job", ["lease_expires_at"], postgresql_where=sa.text("state IN ('leased', 'running')"))
    op.create_index("ix_job_lease_owner_state", "job", ["lease_owner", "state"])

    op.create_table(
        "job_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("at", _timestamp(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("from_state", sa.String(32), nullable=True),
        sa.Column("to_state", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_id", sa.String(36), nullable=True),
        sa.Column("node_id", sa.String(128), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_job_event"),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], name="fk_job_event_job_id_job", ondelete="CASCADE"),
        sa.CheckConstraint(_one_of("kind", JOB_EVENT_KINDS), name="ck_job_event_kind"),
        sa.CheckConstraint(_one_of("from_state", JOB_STATES), name="ck_job_event_from_state"),
        sa.CheckConstraint(_one_of("to_state", JOB_STATES), name="ck_job_event_to_state"),
    )
    op.create_index("ix_job_event_job_id_id", "job_event", ["job_id", "id"])


def downgrade() -> None:
    op.drop_table("job_event")
    op.drop_table("job")
    op.drop_table("node_fingerprint")
    op.drop_table("node_capability")
    op.drop_table("node")
