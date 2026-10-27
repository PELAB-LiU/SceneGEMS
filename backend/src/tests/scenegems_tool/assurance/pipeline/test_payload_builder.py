"""Payloads from the config and earlier results, inline and with references, checked by their job type's models."""

import json

import pytest

from scenegems_tool.assurance.campaign import ClassCatalog, campaign_config_from_dict
from scenegems_tool.assurance.pipeline.payload_builder import (
    PayloadBuilder,
    PayloadError,
    derived_seed,
    required_fingerprints,
    scenario_content_of,
    trajectories_of_trajectory_result,
    validate_payload,
)
from scenegems_tool.assurance.pipeline.stage_graph import SCENE_STEP, Step
from scenegems_tool.cluster.fingerprints.job_images import SCENARIO_EXECUTION_IMAGE, SCENE_GENERATION_IMAGE
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema import PipelineStage
from tests.scenegems_tool.assurance.pipeline.conftest import CLASS_A, config_dict
from tests.scenegems_tool.assurance.pipeline.fake_executor import EXPECTED
from tests.scenegems_tool.cluster.payloads import trajectories_data

REFERENCE = {"sha256": "ab" * 32, "size_bytes": 2048, "kind": "trajectory_data", "media_type": "application/json", "pointer": None}


def _builder(**overrides) -> PayloadBuilder:
    return PayloadBuilder(campaign_config_from_dict(config_dict(**overrides)))


def test_the_scene_payload_carries_the_class_the_domain_and_the_case_seed():
    builder = _builder()
    content_hash = ClassCatalog.default().get(CLASS_A).content_hash
    payload = builder.scene_generation(CLASS_A, content_hash, 1234)
    assert payload["seed"] == 1234 and payload["timeout_s"] == 60 and payload["enforce_low_tcpa"] is False
    assert payload["functional_scenario_content"] == ClassCatalog.default().get(CLASS_A).read_content()
    assert payload["colregs_constraints_content"] == builder.config.domain.colregs_constants
    validate_payload(JobType.SCENE_GENERATION, payload)
    with pytest.raises(PayloadError, match="has changed in the catalog"):
        builder.scene_generation(CLASS_A, "0" * 64, 1234)


def test_the_trajectory_payload_takes_the_scene_inline_as_text_or_as_its_reference():
    builder = _builder()
    inline = builder.trajectory_generation(5, {"valid": True, "evaluation_data": {"best_scene": {"b": 1, "a": 2}}})
    assert json.loads(inline["scenario_content"]) == {"best_scene": {"b": 1, "a": 2}}
    assert inline["params"] == {"generator": "straight", "timespan": 10.0} and inline["seed"] == derived_seed(5, "trajectories") and inline["timeout_s"] == 1800.0
    referenced = builder.trajectory_generation(5, {"valid": True, "evaluation_data": dict(REFERENCE, kind="scene")})
    assert referenced["scenario_content"]["sha256"] == REFERENCE["sha256"]
    for payload in (inline, referenced):
        validate_payload(JobType.TRAJECTORY_GENERATION, payload)
    with pytest.raises(PayloadError, match="no evaluation_data"):
        scenario_content_of({"valid": True})


def test_the_search_generator_sends_its_parameters():
    builder = _builder(trajectories={"generator": "monitor_driven_rrt", "params": {"maxIterations": 50}, "timeout_s": 60})
    payload = builder.trajectory_generation(5, {"evaluation_data": {}})
    assert payload["params"] == {"generator": "monitor_driven_rrt", "maxIterations": 50} and payload["timeout_s"] == 60.0
    validate_payload(JobType.TRAJECTORY_GENERATION, payload)


def test_the_simulation_takes_the_trajectories_inline_or_through_a_pointer():
    builder = _builder(runs=[{"monitor": "live", "early_stop": True, "stack": {"mode": "usv_navigation", "dt": 1.0}}])
    inline = builder.simulation(5, 0, {"trajectory_data": {"trajectories": trajectories_data()}})
    assert inline["trajectories"] == trajectories_data()
    assert (inline["mode"], inline["monitor"], inline["early_stop"], inline["dt"]) == ("usv_navigation", "live", True, 1.0)
    assert inline["seed"] == builder.config.execution.runs[0].seed_for(5, 0)
    assert inline["colregs_constraints_content"] == builder.config.domain.colregs_constants
    referenced = builder.simulation(5, 0, {"trajectory_data": REFERENCE})
    assert referenced["trajectories"] == dict(REFERENCE, pointer="/trajectories")
    for payload in (inline, referenced):
        validate_payload(JobType.SIMULATION_KINEMATIC, payload)
    assert trajectories_of_trajectory_result({"trajectory_data": dict(REFERENCE, pointer="/result")})["pointer"] == "/result/trajectories"


def test_a_run_without_the_live_monitor_runs_none():
    payload = _builder(runs=[{"monitor": "empty"}]).simulation(5, 0, {"trajectory_data": {"trajectories": trajectories_data()}})
    assert "monitor" not in payload and "early_stop" not in payload


def test_monitoring_and_calibration_take_the_state_logs():
    builder = _builder(policy={"keep_frames": True})
    log = dict(REFERENCE, kind="trajectories")
    monitoring = builder.post_hoc_monitoring("case#0#run0", {"trajectories": log})
    assert monitoring["trajectories"] == log and monitoring["include_frames"] is True and monitoring["scenario_id"] == "case#0#run0"
    validate_payload(JobType.MONITORING_POST_HOC, monitoring)
    calibration = builder.calibration("case#0", {"mode": "replay"}, [{"trajectories": log}, {"trajectories": trajectories_data()}])
    assert calibration["trajectories"][0] == log and calibration["reference"] == "case#0"
    validate_payload(JobType.CALIBRATION_DEVIATION, calibration)


def test_a_submission_requires_the_pinned_fingerprints_of_its_images_and_the_labels():
    builder = _builder(resources={"required_labels": {"site": "lab"}, "priority": 5})
    payload = builder.scene_generation(CLASS_A, ClassCatalog.default().get(CLASS_A).content_hash, 3)
    submission = builder.submission(SCENE_STEP, payload, "key", EXPECTED)
    assert submission.requirements.fingerprints == {SCENE_GENERATION_IMAGE: EXPECTED[SCENE_GENERATION_IMAGE]}
    assert submission.requirements.labels == {"site": "lab"} and submission.priority == 5 and submission.idempotency_key == "key"
    assert submission.allowed_nodes == []  # any node
    assert required_fingerprints(JobType.CALIBRATION_DEVIATION, {}, EXPECTED) == {SCENARIO_EXECUTION_IMAGE: "fp-execution"}
    with pytest.raises(PayloadError, match="invalid simulation.kinematic payload"):
        builder.submission(Step(PipelineStage.SIMULATE, 0, 0), {"trajectories": {"scene_list": []}}, "key", EXPECTED)


def test_a_submission_names_the_campaigns_selected_nodes():
    builder = _builder(resources={"nodes": ["lab-1", "lab-3"]})
    payload = builder.scene_generation(CLASS_A, ClassCatalog.default().get(CLASS_A).content_hash, 3)
    submission = builder.submission(SCENE_STEP, payload, "key", EXPECTED)
    assert submission.allowed_nodes == ["lab-1", "lab-3"] and submission.requirements.labels == {}


def test_derived_seeds_are_stable_and_distinct():
    assert derived_seed(1, "trajectories") == derived_seed(1, "trajectories")
    assert derived_seed(1, "trajectories") != derived_seed(2, "trajectories")
    assert 0 <= derived_seed(99, "trajectories") < 2**31
