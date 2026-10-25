import pytest

from scenegems_tool.persistence.schema import (
    ArtifactReferenceRow,
    CalibrationResultRow,
    CampaignActualState,
    CampaignClassRow,
    CaseState,
    PipelineJobRow,
    RunRecordRow,
    ScenarioCaseRow,
    VerdictRow,
)
from scenegems_tool.persistence.schema.artifact_tables import require_sha256_hex, sha256_hex_check

MAX_IDENTIFIER = 63  # Postgres truncates longer names


def _names(table):
    return {constraint.name for constraint in table.constraints} | {index.name for index in table.indexes}


def test_every_name_fits_postgres():
    from scenegems_tool.persistence.schema import Base

    too_long = sorted(name for table in Base.metadata.tables.values() for name in _names(table) if name and len(name) > MAX_IDENTIFIER)
    assert too_long == []


def test_hash_columns_hold_sha256_hex():
    assert "ck_scenario_case_scene_artifact_is_sha256_hex" in _names(ScenarioCaseRow.__table__)
    assert "ck_campaign_class_content_hash_is_sha256_hex" in _names(CampaignClassRow.__table__)
    assert sha256_hex_check("hash") == "hash ~ '^[0-9a-f]{64}$'"
    assert sha256_hex_check("scene", nullable=True) == "scene IS NULL OR scene ~ '^[0-9a-f]{64}$'"


@pytest.mark.parametrize("value", ["a" * 63, "A" * 64, "g" * 64, None, 12])
def test_require_sha256_hex_refuses(value):
    with pytest.raises(ValueError):
        require_sha256_hex(value)


def test_require_sha256_hex_accepts():
    assert require_sha256_hex("0f" * 32) == "0f" * 32


def test_keys_of_the_engine_and_the_api():
    assert "uq_scenario_case_campaign_id_class_id_case_index" in _names(ScenarioCaseRow.__table__)
    assert {"uq_pipeline_job_idempotency_key", "uq_pipeline_job_job_id", "ix_pipeline_job_intents"} <= _names(PipelineJobRow.__table__)
    assert "uq_run_record_case_id_run_index_repeat_index" in _names(RunRecordRow.__table__)
    assert {"uq_verdict_case_id_run_index", "ix_verdict_campaign_id_class_id_state", "ck_verdict_unmonitored_by_the_empty_monitor"} <= _names(VerdictRow.__table__)
    assert "uq_artifact_reference_artifact_hash_holder_kind_holder_id_role" in _names(ArtifactReferenceRow.__table__)
    assert "uq_calibration_result_key" in _names(CalibrationResultRow.__table__)


def test_intent_index_covers_intents_only():
    index = next(index for index in PipelineJobRow.__table__.indexes if index.name == "ix_pipeline_job_intents")
    assert str(index.dialect_options["postgresql"]["where"]) == "job_id IS NULL"


def test_artifacts_are_not_foreign_keys_of_cases_and_runs():
    # Retention deletes artifacts that cases and runs still name, once their references are gone
    assert not ScenarioCaseRow.__table__.c.scene_artifact.foreign_keys
    (foreign_key,) = ArtifactReferenceRow.__table__.c.artifact_hash.foreign_keys
    assert foreign_key.ondelete == "RESTRICT"


def test_final_states():
    assert {state for state in CampaignActualState if state.is_final} == {CampaignActualState.STOPPED, CampaignActualState.COMPLETED}
    assert {state for state in CaseState if not state.is_final} == {CaseState.ACTIVE}
