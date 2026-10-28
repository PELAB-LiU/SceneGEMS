"""Partial campaigns: campaign kinds and origins, case inputs, step verdicts, run sources, upload references.

New columns: campaign.kind and campaign.origin, scenario_case.input_artifact and
input_source, verdict.step, run_record.source, artifact_reference.expires_at. Existing
campaigns become kind campaign without an origin, existing verdicts judge the simulation
step, existing run records come from a job. The pipeline stages gain monitor_scene and
monitor_trajectories, the artifact holders upload; run_record.trajectory_generator may be
empty; a verdict is unique per case, step and run.

The downgrade drops the new columns, so workbench entries stay as ordinary campaigns. It
fails while rows of the new shape exist (a verdict of the scene or trajectory step, a run
record without a generator, a case or job at a monitor stage, an upload reference), which
is the safe outcome.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum values as of this revision; a later revision that adds a value replaces the constraint.
CAMPAIGN_KINDS = ("campaign", "workbench")
CAMPAIGN_ORIGINS = ("wizard", "cli", "scene_generation", "trajectory_generation", "simulation", "live_session")
STEP_KINDS = ("scene", "trajectories", "simulation")
RUN_SOURCES = ("job", "live_session")
PREVIOUS_PIPELINE_STAGES = ("generate_scene", "generate_trajectories", "simulate", "monitor", "calibrate", "verdict")
PIPELINE_STAGES = ("generate_scene", "monitor_scene", "generate_trajectories", "monitor_trajectories", "simulate", "monitor", "calibrate", "verdict")
PREVIOUS_ARTIFACT_HOLDER_KINDS = ("campaign", "case", "run", "job", "calibration")
ARTIFACT_HOLDER_KINDS = PREVIOUS_ARTIFACT_HOLDER_KINDS + ("upload",)

SHA256_HEX = "'^[0-9a-f]{64}$'"
KIND_OF_ORIGIN = "origin IS NULL OR (kind = 'campaign') = (origin IN ('wizard', 'cli'))"


def _one_of(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, condition)


def _replace_stage_constraints(stages: Sequence[str]) -> None:
    for table in ("scenario_case", "pipeline_job"):
        _replace_check(table, f"ck_{table}_stage", _one_of("stage", stages))


def _add_filled_column(table: str, column: str, value: str) -> None:
    """A not null string column whose existing rows get value."""
    op.add_column(table, sa.Column(column, sa.String(32), nullable=True))
    op.execute(f"UPDATE {table} SET {column} = '{value}'")
    op.alter_column(table, column, nullable=False)


def upgrade() -> None:
    _add_filled_column("campaign", "kind", "campaign")
    op.add_column("campaign", sa.Column("origin", sa.String(32), nullable=True))
    op.create_check_constraint("ck_campaign_kind", "campaign", _one_of("kind", CAMPAIGN_KINDS))
    op.create_check_constraint("ck_campaign_origin", "campaign", _one_of("origin", CAMPAIGN_ORIGINS))
    op.create_check_constraint("ck_campaign_origin_of_the_kind", "campaign", KIND_OF_ORIGIN)
    op.create_index("ix_campaign_kind_created_at", "campaign", ["kind", "created_at"])

    _replace_stage_constraints(PIPELINE_STAGES)
    op.add_column("scenario_case", sa.Column("input_artifact", sa.String(64), nullable=True))
    op.add_column("scenario_case", sa.Column("input_source", postgresql.JSONB(), nullable=True))
    op.create_check_constraint("ck_scenario_case_input_artifact_is_sha256_hex", "scenario_case", f"input_artifact IS NULL OR input_artifact ~ {SHA256_HEX}")

    _add_filled_column("verdict", "step", "simulation")
    op.create_check_constraint("ck_verdict_step", "verdict", _one_of("step", STEP_KINDS))
    op.create_check_constraint("ck_verdict_one_verdict_per_generation_step", "verdict", "step = 'simulation' OR run_index = 0")
    op.drop_constraint("uq_verdict_case_id_run_index", "verdict", type_="unique")
    op.create_unique_constraint("uq_verdict_case_id_step_run_index", "verdict", ["case_id", "step", "run_index"])
    op.create_index("ix_verdict_campaign_id_step_state", "verdict", ["campaign_id", "step", "state"])

    _add_filled_column("run_record", "source", "job")
    op.create_check_constraint("ck_run_record_source", "run_record", _one_of("source", RUN_SOURCES))
    op.alter_column("run_record", "trajectory_generator", nullable=True)

    _replace_check("artifact_reference", "ck_artifact_reference_holder_kind", _one_of("holder_kind", ARTIFACT_HOLDER_KINDS))
    op.add_column("artifact_reference", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_artifact_reference_uploads_expire", "artifact_reference", "(holder_kind = 'upload') = (expires_at IS NOT NULL)")
    op.create_index("ix_artifact_reference_expires_at", "artifact_reference", ["expires_at"], postgresql_where=sa.text("expires_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_artifact_reference_expires_at", table_name="artifact_reference")
    op.drop_constraint("ck_artifact_reference_uploads_expire", "artifact_reference", type_="check")
    op.drop_column("artifact_reference", "expires_at")
    _replace_check("artifact_reference", "ck_artifact_reference_holder_kind", _one_of("holder_kind", PREVIOUS_ARTIFACT_HOLDER_KINDS))

    op.alter_column("run_record", "trajectory_generator", nullable=False)
    op.drop_column("run_record", "source")  # drops its check constraint with it

    # Refuses verdicts of the scene and trajectory steps, which the old table cannot tell from a run's
    op.create_check_constraint("ck_verdict_downgrade_simulation_only", "verdict", "step = 'simulation'")
    op.drop_constraint("ck_verdict_downgrade_simulation_only", "verdict", type_="check")
    op.drop_index("ix_verdict_campaign_id_step_state", table_name="verdict")
    op.drop_constraint("uq_verdict_case_id_step_run_index", "verdict", type_="unique")
    op.create_unique_constraint("uq_verdict_case_id_run_index", "verdict", ["case_id", "run_index"])
    op.drop_column("verdict", "step")

    op.drop_column("scenario_case", "input_source")
    op.drop_column("scenario_case", "input_artifact")
    _replace_stage_constraints(PREVIOUS_PIPELINE_STAGES)

    op.drop_index("ix_campaign_kind_created_at", table_name="campaign")
    op.drop_constraint("ck_campaign_origin_of_the_kind", "campaign", type_="check")
    op.drop_column("campaign", "origin")
    op.drop_column("campaign", "kind")
