"""Campaigns, pipeline, results and artifacts; job availability and event transaction ids.

New tables: campaign, campaign_config_version, campaign_class, scenario_case, pipeline_job,
pipeline_cursor, run_record, verdict, campaign_event, artifact, artifact_reference,
calibration_result. New columns: job.available_at (existing jobs get their submission
time) and job_event.tx_id (existing events get this migration's transaction id). The job
type constraints gain calibration.deviation.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum values as of this revision; a later revision that adds a value replaces the constraint.
PREVIOUS_JOB_TYPES = ("scene_generation", "trajectory_generation", "simulation.kinematic", "simulation.ardupilot", "monitoring.post_hoc")
JOB_TYPES = PREVIOUS_JOB_TYPES + ("calibration.deviation",)
CAMPAIGN_DESIRED_STATES = ("running", "paused", "draining", "stopped")
CAMPAIGN_ACTUAL_STATES = ("created", "running", "paused", "draining", "stalled", "stopped", "completed")
CAMPAIGN_CLASS_STATES = ("open", "complete", "abandoned")
PIPELINE_STAGES = ("generate_scene", "generate_trajectories", "simulate", "monitor", "calibrate", "verdict")
CASE_STATES = ("active", "complete", "dropped", "failed", "cancelled")
TRAJECTORY_GENERATORS = ("monitor_driven_rrt", "straight")
MONITORS = ("post_hoc", "live", "empty")
VERDICT_STATES = ("passed", "failed", "unmonitored")
CAMPAIGN_EVENT_KINDS = (
    "created",
    "desired_state_changed",
    "started",
    "paused",
    "resumed",
    "draining",
    "stalled",
    "stopped",
    "completed",
    "class_complete",
    "class_abandoned",
    "engine_started",
    "note",
)
ARTIFACT_HOLDER_KINDS = ("campaign", "case", "run", "job", "calibration")

SHA256_HEX = "'^[0-9a-f]{64}$'"
CURRENT_TRANSACTION_ID = "(pg_current_xact_id()::text::bigint)"


def _one_of(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _sha256(column: str, nullable: bool = False) -> str:
    check = f"{column} ~ {SHA256_HEX}"
    return f"{column} IS NULL OR {check}" if nullable else check


def _timestamp() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def _replace_job_type_constraints(job_types: Sequence[str]) -> None:
    for table in ("job", "node_capability"):
        op.drop_constraint(f"ck_{table}_job_type", table, type_="check")
        op.create_check_constraint(f"ck_{table}_job_type", table, _one_of("job_type", job_types))


def upgrade() -> None:
    _replace_job_type_constraints(JOB_TYPES)

    op.add_column("job", sa.Column("available_at", _timestamp(), nullable=True))
    op.execute("UPDATE job SET available_at = submitted_at")
    op.alter_column("job", "available_at", nullable=False)
    op.add_column("job_event", sa.Column("tx_id", sa.BigInteger(), server_default=sa.text(CURRENT_TRANSACTION_ID), nullable=False))
    op.create_index("ix_job_event_tx_id_id", "job_event", ["tx_id", "id"])

    op.create_table(
        "campaign",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("desired_state", sa.String(32), nullable=False),
        sa.Column("actual_state", sa.String(32), nullable=False),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("pinned_fingerprints", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.Column("updated_at", _timestamp(), nullable=False),
        sa.Column("started_at", _timestamp(), nullable=True),
        sa.Column("finished_at", _timestamp(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_campaign"),
        sa.CheckConstraint(_one_of("desired_state", CAMPAIGN_DESIRED_STATES), name="ck_campaign_desired_state"),
        sa.CheckConstraint(_one_of("actual_state", CAMPAIGN_ACTUAL_STATES), name="ck_campaign_actual_state"),
        sa.CheckConstraint("config_version >= 1", name="ck_campaign_config_version_positive"),
        sa.CheckConstraint("actual_state NOT IN ('stopped', 'completed') OR finished_at IS NOT NULL", name="ck_campaign_finished_when_final"),
    )
    op.create_index("ix_campaign_created_at", "campaign", ["created_at"])

    op.create_table(
        "campaign_config_version",
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("campaign_id", "version", name="pk_campaign_config_version"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], name="fk_campaign_config_version_campaign_id_campaign", ondelete="CASCADE"),
        sa.CheckConstraint("version >= 1", name="ck_campaign_config_version_version_positive"),
        sa.CheckConstraint(_sha256("config_hash"), name="ck_campaign_config_version_config_hash_is_sha256_hex"),
    )

    op.create_table(
        "campaign_class",
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(256), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("vessel_count", sa.Integer(), nullable=False),
        sa.Column("obstacle_count", sa.Integer(), nullable=False),
        sa.Column("quota", sa.Integer(), nullable=False),
        sa.Column("failure_budget", sa.Integer(), nullable=False),
        sa.Column("complete_count", sa.Integer(), nullable=False),
        sa.Column("dropped_count", sa.Integer(), nullable=False),
        sa.Column("in_flight_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.Column("updated_at", _timestamp(), nullable=False),
        sa.Column("finished_at", _timestamp(), nullable=True),
        sa.PrimaryKeyConstraint("campaign_id", "class_id", name="pk_campaign_class"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], name="fk_campaign_class_campaign_id_campaign", ondelete="CASCADE"),
        sa.CheckConstraint(_one_of("state", CAMPAIGN_CLASS_STATES), name="ck_campaign_class_state"),
        sa.CheckConstraint(_sha256("content_hash"), name="ck_campaign_class_content_hash_is_sha256_hex"),
        sa.CheckConstraint("quota >= 1", name="ck_campaign_class_quota_positive"),
        sa.CheckConstraint("failure_budget >= 0", name="ck_campaign_class_failure_budget_not_negative"),
        sa.CheckConstraint("vessel_count >= 1 AND obstacle_count >= 0", name="ck_campaign_class_counts_of_the_scenario"),
        sa.CheckConstraint("complete_count >= 0 AND dropped_count >= 0 AND in_flight_count >= 0", name="ck_campaign_class_case_counts_not_negative"),
        sa.CheckConstraint("state = 'open' OR finished_at IS NOT NULL", name="ck_campaign_class_finished_when_closed"),
    )
    op.create_index("ix_campaign_class_campaign_id_state", "campaign_class", ["campaign_id", "state"])

    op.create_table(
        "scenario_case",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(256), nullable=False),
        sa.Column("case_index", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scene_artifact", sa.String(64), nullable=True),
        sa.Column("trajectories_artifact", sa.String(64), nullable=True),
        sa.Column("trajectories_complete", sa.Boolean(), nullable=True),
        sa.Column("progress", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.Column("updated_at", _timestamp(), nullable=False),
        sa.Column("finished_at", _timestamp(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_scenario_case"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], name="fk_scenario_case_campaign_id_campaign", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id", "class_id"], ["campaign_class.campaign_id", "campaign_class.class_id"], name="fk_scenario_case_campaign_class", ondelete="CASCADE"),
        sa.UniqueConstraint("campaign_id", "class_id", "case_index", name="uq_scenario_case_campaign_id_class_id_case_index"),
        sa.CheckConstraint(_one_of("stage", PIPELINE_STAGES), name="ck_scenario_case_stage"),
        sa.CheckConstraint(_one_of("state", CASE_STATES), name="ck_scenario_case_state"),
        sa.CheckConstraint("case_index >= 0", name="ck_scenario_case_case_index_not_negative"),
        sa.CheckConstraint("seed >= 0", name="ck_scenario_case_seed_not_negative"),
        sa.CheckConstraint("version >= 1", name="ck_scenario_case_version_positive"),
        sa.CheckConstraint(_sha256("scene_artifact", nullable=True), name="ck_scenario_case_scene_artifact_is_sha256_hex"),
        sa.CheckConstraint(_sha256("trajectories_artifact", nullable=True), name="ck_scenario_case_trajectories_artifact_is_sha256_hex"),
        sa.CheckConstraint("(state = 'active') = (finished_at IS NULL)", name="ck_scenario_case_finished_when_final"),
    )
    op.create_index("ix_scenario_case_campaign_id_state", "scenario_case", ["campaign_id", "state"])

    op.create_table(
        "pipeline_job",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("run_index", sa.Integer(), nullable=True),
        sa.Column("repeat_index", sa.Integer(), nullable=True),
        sa.Column("submission", postgresql.JSONB(), nullable=True),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.Column("submitted_at", _timestamp(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_pipeline_job"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], name="fk_pipeline_job_campaign_id_campaign", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["scenario_case.id"], name="fk_pipeline_job_case_id_scenario_case", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], name="fk_pipeline_job_job_id_job"),
        sa.UniqueConstraint("idempotency_key", name="uq_pipeline_job_idempotency_key"),
        sa.UniqueConstraint("job_id", name="uq_pipeline_job_job_id"),
        sa.CheckConstraint(_one_of("stage", PIPELINE_STAGES), name="ck_pipeline_job_stage"),
        sa.CheckConstraint("run_index IS NULL OR run_index >= 0", name="ck_pipeline_job_run_index_not_negative"),
        sa.CheckConstraint("stage <> 'verdict'", name="ck_pipeline_job_stage_runs_as_a_job"),
        sa.CheckConstraint("(job_id IS NULL) = (submitted_at IS NULL)", name="ck_pipeline_job_submitted_when_linked"),
    )
    op.create_index("ix_pipeline_job_case_id", "pipeline_job", ["case_id"])
    op.create_index("ix_pipeline_job_campaign_id_stage", "pipeline_job", ["campaign_id", "stage"])
    op.create_index("ix_pipeline_job_intents", "pipeline_job", ["campaign_id", "id"], postgresql_where=sa.text("job_id IS NULL"))

    op.create_table(
        "pipeline_cursor",
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("last_tx_id", sa.BigInteger(), nullable=False),
        sa.Column("last_event_id", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", _timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("name", name="pk_pipeline_cursor"),
        sa.CheckConstraint("last_tx_id >= 0 AND last_event_id >= 0", name="ck_pipeline_cursor_position_not_negative"),
    )

    op.create_table(
        "run_record",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(256), nullable=False),
        sa.Column("run_index", sa.Integer(), nullable=False),
        sa.Column("repeat_index", sa.Integer(), nullable=False),
        sa.Column("trajectory_generator", sa.String(32), nullable=False),
        sa.Column("trajectories_complete", sa.Boolean(), nullable=False),
        sa.Column("stack", postgresql.JSONB(), nullable=False),
        sa.Column("repeatability_tier", sa.String(32), nullable=True),
        sa.Column("environment", postgresql.JSONB(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("dt", sa.Float(), nullable=True),
        sa.Column("steps", sa.Integer(), nullable=True),
        sa.Column("state_digest", sa.String(128), nullable=True),
        sa.Column("artifacts", postgresql.JSONB(), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("node_id", sa.String(128), nullable=True),
        sa.Column("fingerprints", postgresql.JSONB(), nullable=False),
        sa.Column("durations_s", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_run_record"),
        sa.ForeignKeyConstraint(["case_id"], ["scenario_case.id"], name="fk_run_record_case_id_scenario_case", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], name="fk_run_record_campaign_id_campaign", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"], name="fk_run_record_job_id_job"),
        sa.UniqueConstraint("case_id", "run_index", "repeat_index", name="uq_run_record_case_id_run_index_repeat_index"),
        sa.CheckConstraint(_one_of("trajectory_generator", TRAJECTORY_GENERATORS), name="ck_run_record_trajectory_generator"),
        sa.CheckConstraint("run_index >= 0 AND repeat_index >= 0", name="ck_run_record_indexes_not_negative"),
        sa.CheckConstraint("seed >= 0", name="ck_run_record_seed_not_negative"),
        sa.CheckConstraint("steps IS NULL OR steps >= 0", name="ck_run_record_steps_not_negative"),
    )
    op.create_index("ix_run_record_campaign_id_class_id", "run_record", ["campaign_id", "class_id"])

    op.create_table(
        "verdict",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("case_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(256), nullable=False),
        sa.Column("run_index", sa.Integer(), nullable=False),
        sa.Column("run_record_id", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("monitor", sa.String(32), nullable=False),
        sa.Column("rule_outcomes", postgresql.JSONB(), nullable=False),
        sa.Column("failed_rules", postgresql.JSONB(), nullable=False),
        sa.Column("first_failure_time_s", sa.Float(), nullable=True),
        sa.Column("margin", sa.Float(), nullable=True),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column("early_stop_time_s", sa.Float(), nullable=True),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_verdict"),
        sa.ForeignKeyConstraint(["case_id"], ["scenario_case.id"], name="fk_verdict_case_id_scenario_case", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], name="fk_verdict_campaign_id_campaign", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_record_id"], ["run_record.id"], name="fk_verdict_run_record_id_run_record", ondelete="SET NULL"),
        sa.UniqueConstraint("case_id", "run_index", name="uq_verdict_case_id_run_index"),
        sa.CheckConstraint(_one_of("state", VERDICT_STATES), name="ck_verdict_state"),
        sa.CheckConstraint(_one_of("monitor", MONITORS), name="ck_verdict_monitor"),
        sa.CheckConstraint("run_index >= 0", name="ck_verdict_run_index_not_negative"),
        sa.CheckConstraint("(state = 'unmonitored') = (monitor = 'empty')", name="ck_verdict_unmonitored_by_the_empty_monitor"),
        sa.CheckConstraint("early_stop_time_s IS NULL OR monitor = 'live'", name="ck_verdict_early_stop_by_the_live_monitor"),
        sa.CheckConstraint("first_failure_time_s IS NULL OR state = 'failed'", name="ck_verdict_failure_time_only_when_failed"),
    )
    op.create_index("ix_verdict_campaign_id_class_id_state", "verdict", ["campaign_id", "class_id", "state"])
    op.create_index("ix_verdict_campaign_id_state", "verdict", ["campaign_id", "state"])

    op.create_table(
        "campaign_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("at", _timestamp(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("class_id", sa.String(256), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_event"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], name="fk_campaign_event_campaign_id_campaign", ondelete="CASCADE"),
        sa.CheckConstraint(_one_of("kind", CAMPAIGN_EVENT_KINDS), name="ck_campaign_event_kind"),
    )
    op.create_index("ix_campaign_event_campaign_id_id", "campaign_event", ["campaign_id", "id"])

    op.create_table(
        "artifact",
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("stored_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.Column("last_used_at", _timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("hash", name="pk_artifact"),
        sa.CheckConstraint(_sha256("hash"), name="ck_artifact_hash_is_sha256_hex"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_artifact_size_not_negative"),
        sa.CheckConstraint("stored_size_bytes IS NULL OR stored_size_bytes >= 0", name="ck_artifact_stored_size_not_negative"),
    )
    op.create_index("ix_artifact_last_used_at", "artifact", ["last_used_at"])

    op.create_table(
        "artifact_reference",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("holder_kind", sa.String(32), nullable=False),
        sa.Column("holder_id", sa.String(64), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=True),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_artifact_reference"),
        sa.ForeignKeyConstraint(["artifact_hash"], ["artifact.hash"], name="fk_artifact_reference_artifact_hash_artifact", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], name="fk_artifact_reference_campaign_id_campaign", ondelete="CASCADE"),
        sa.UniqueConstraint("artifact_hash", "holder_kind", "holder_id", "role", name="uq_artifact_reference_artifact_hash_holder_kind_holder_id_role"),
        sa.CheckConstraint(_one_of("holder_kind", ARTIFACT_HOLDER_KINDS), name="ck_artifact_reference_holder_kind"),
    )
    op.create_index("ix_artifact_reference_holder_kind_holder_id", "artifact_reference", ["holder_kind", "holder_id"])
    op.create_index("ix_artifact_reference_campaign_id", "artifact_reference", ["campaign_id"])

    op.create_table(
        "calibration_result",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("stack", postgresql.JSONB(), nullable=False),
        sa.Column("stack_hash", sa.String(64), nullable=False),
        sa.Column("fingerprints", postgresql.JSONB(), nullable=False),
        sa.Column("fingerprints_hash", sa.String(64), nullable=False),
        sa.Column("environment", postgresql.JSONB(), nullable=False),
        sa.Column("environment_hash", sa.String(64), nullable=False),
        sa.Column("reference_scenario", sa.String(256), nullable=False),
        sa.Column("repeats", sa.Integer(), nullable=False),
        sa.Column("exact", sa.Boolean(), nullable=False),
        sa.Column("deviation_bound_m", sa.Float(), nullable=True),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
        sa.Column("campaign_id", sa.String(36), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.Column("updated_at", _timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_calibration_result"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"], name="fk_calibration_result_campaign_id_campaign", ondelete="SET NULL"),
        sa.UniqueConstraint("stack_hash", "fingerprints_hash", "environment_hash", "reference_scenario", name="uq_calibration_result_key"),
        sa.CheckConstraint(_sha256("stack_hash"), name="ck_calibration_result_stack_hash_is_sha256_hex"),
        sa.CheckConstraint(_sha256("fingerprints_hash"), name="ck_calibration_result_fingerprints_hash_is_sha256_hex"),
        sa.CheckConstraint(_sha256("environment_hash"), name="ck_calibration_result_environment_hash_is_sha256_hex"),
        sa.CheckConstraint("repeats >= 1", name="ck_calibration_result_repeats_positive"),
        sa.CheckConstraint("deviation_bound_m IS NULL OR deviation_bound_m >= 0", name="ck_calibration_result_deviation_bound_not_negative"),
    )
    op.create_index("ix_calibration_result_stack_hash_fingerprints_hash", "calibration_result", ["stack_hash", "fingerprints_hash"])


def downgrade() -> None:
    op.drop_table("calibration_result")
    op.drop_table("artifact_reference")
    op.drop_table("artifact")
    op.drop_table("campaign_event")
    op.drop_table("verdict")
    op.drop_table("run_record")
    op.drop_table("pipeline_cursor")
    op.drop_table("pipeline_job")
    op.drop_table("scenario_case")
    op.drop_table("campaign_class")
    op.drop_table("campaign_config_version")
    op.drop_table("campaign")
    op.drop_index("ix_job_event_tx_id_id", table_name="job_event")
    op.drop_column("job_event", "tx_id")
    op.drop_column("job", "available_at")
    # Fails while jobs or capabilities of the newer type exist, which is the safe outcome
    _replace_job_type_constraints(PREVIOUS_JOB_TYPES)
