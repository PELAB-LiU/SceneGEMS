import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scenegems_tool.assurance.campaign.campaign_config import (
    DEFAULT_COLREGS_CONSTANTS_FILE,
    DEFAULT_OBSTACLE_TYPES_FILE,
    DEFAULT_VESSEL_TYPES_FILE,
    MAX_SEED,
    CampaignConfig,
    CampaignConfigError,
    QueueDepthCaps,
    RetentionPolicy,
    RunConfig,
    campaign_config_from_dict,
    case_seed,
    load_campaign_config,
    parse_campaign_config,
    run_seed,
)
from scenegems_tool.cluster.node.jobs.simulation_kinematic_job import KinematicMode
from scenegems_tool.persistence.canonical_json import canonical_json
from scenegems_tool.persistence.schema import MonitorImplementation, PipelineStage, TrajectoryGeneratorImplementation

DATA = Path(__file__).parent / "data"
EXIT_CAMPAIGN = DATA / "exit_campaign.yaml"
MINIMAL = {"name": "lab", "scope": [{"classes": ["2vessel_0obstacle_scenarios/functional_model0"], "quota": 2}]}


def _with(**sections) -> dict:
    return dict(MINIMAL, **sections)


def _reasons(data) -> str:
    with pytest.raises(CampaignConfigError) as error:
        campaign_config_from_dict(data) if isinstance(data, dict) else parse_campaign_config(data)
    return "\n".join(error.value.reasons)


# Defaults


def test_a_minimal_config_gets_the_defaults():
    config = campaign_config_from_dict(MINIMAL)
    assert config.format == 1 and config.scope[0].failure_budget == 0
    assert config.domain.colregs_constants == DEFAULT_COLREGS_CONSTANTS_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "\r" not in config.domain.vessel_types and "MiniUSV" in config.domain.vessel_types
    assert config.domain.obstacle_types == DEFAULT_OBSTACLE_TYPES_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert (config.domain.scene_generation_timeout_s, config.domain.enforce_low_tcpa) == (60, False)
    assert (config.trajectories.generator, config.trajectories.params, config.trajectories.timeout_s) == (TrajectoryGeneratorImplementation.MONITOR_DRIVEN_RRT, {}, 1800.0)
    (run,) = config.execution.runs
    assert (run.stack.simulation_layer, run.stack.mode, run.monitor, run.repeats, run.seed, run.early_stop) == ("kinematic", KinematicMode.REPLAY, MonitorImplementation.POST_HOC, 1, None, False)
    assert (config.policy.retention, config.policy.keep_frames, config.policy.seed) == (RetentionPolicy.ALL, False, 0)
    assert config.resources.queue_depth.cap(PipelineStage.SIMULATE) == 32 and config.resources.required_labels == {}
    assert config.resources.nodes == ()  # every node
    assert DEFAULT_VESSEL_TYPES_FILE.name == "vessel_types.yaml"


def test_the_exit_campaign_sample():
    config = load_campaign_config(EXIT_CAMPAIGN)
    assert config.name == "phase 4 exit campaign"
    (entry,) = config.scope
    assert (entry.patterns, entry.quota, entry.failure_budget) == (("2vessel_*_scenarios", "3vessel_*_scenarios"), 15, 15)
    (run,) = config.execution.runs
    assert (run.name, run.stack.mode, run.monitor, run.repeats) == ("usv_navigation", KinematicMode.USV_NAVIGATION, MonitorImplementation.POST_HOC, 1)
    assert config.policy.seed == 20261025


def test_the_queue_depth_caps_cover_every_job_stage():
    caps = QueueDepthCaps(simulate=4)
    assert [caps.cap(stage) for stage in PipelineStage if stage != PipelineStage.VERDICT] == [16, 16, 4, 32, 8]
    with pytest.raises(ValueError):
        caps.cap(PipelineStage.VERDICT)


def test_the_straight_generator_and_search_parameters():
    straight = campaign_config_from_dict(_with(trajectories={"generator": "straight", "timespan_s": 600}))
    assert (straight.trajectories.generator, straight.trajectories.timespan_s) == (TrajectoryGeneratorImplementation.STRAIGHT, 600.0)
    tuned = campaign_config_from_dict(_with(trajectories={"params": {"maxIterations": 5000, "directionThreshold": 0.5, "includeMonitorResults": False}}))
    assert tuned.trajectories.params == {"maxIterations": 5000, "directionThreshold": 0.5, "includeMonitorResults": False}


def test_live_monitor_with_early_stop_and_usv_navigation_parameters():
    usv_navigation = {"goal": [100.0, 0.0], "speed": 5.0, "safety_radius": 120.0, "control_horizon": 60.0}
    config = campaign_config_from_dict(
        _with(execution={"runs": [{"stack": {"mode": "usv_navigation", "usv_navigation": usv_navigation}, "monitor": "live", "early_stop": True, "seed": 9, "repeats": 3}]})
    )
    (run,) = config.execution.runs
    assert (run.monitor, run.early_stop, run.repeats, run.stack.usv_navigation.safety_radius) == (MonitorImplementation.LIVE, True, 3, 120.0)


# Rejections


@pytest.mark.parametrize(
    "data, reason",
    [
        (dict(MINIMAL, colour="blue"), "colour: Extra inputs are not permitted"),
        (_with(scope=[{"classes": ["a/b"], "quota": 1, "weight": 2}]), "scope.0.weight: Extra inputs are not permitted"),
        (_with(scope=[]), "scope: Tuple should have at least 1 item"),
        (_with(scope=[{"quota": 1}]), "a scope entry needs classes or patterns"),
        (_with(scope=[{"classes": ["a/b"], "quota": 0}]), "scope.0.quota: Input should be greater than or equal to 1"),
        (_with(scope=[{"classes": ["a/b"], "quota": 1, "failure_budget": -1}]), "scope.0.failure_budget"),
        ({"scope": MINIMAL["scope"]}, "name: Field required"),
        (_with(format=2), "format: Input should be 1"),
        (_with(trajectories={"generator": "straight"}), "the straight generator needs timespan_s"),
        (_with(trajectories={"generator": "straight", "timespan_s": 60, "params": {"maxIterations": 5}}), "the straight generator takes no search parameters"),
        (_with(trajectories={"timespan_s": 60}), "timespan_s applies to the straight generator only"),
        (_with(trajectories={"params": {"maxIteration": 5}}), "unknown search parameters ['maxIteration']"),
        (_with(trajectories={"params": {"timespan": 60}}), "unknown search parameters ['timespan']"),
        (_with(trajectories={"generator": "astar"}), "trajectories.generator: Input should be 'monitor_driven_rrt' or 'straight'"),
        (_with(execution={"runs": []}), "execution.runs: Tuple should have at least 1 item"),
        (_with(execution={"runs": [{"early_stop": True}]}), "early_stop needs the live monitor"),
        (_with(execution={"runs": [{"monitor": "eventually"}]}), "execution.runs.0.monitor"),
        (_with(execution={"runs": [{"stack": {"simulation_layer": "gazebo"}}]}), "execution.runs.0.stack.simulation_layer: Input should be 'kinematic'"),
        (
            _with(execution={"runs": [{"stack": {"usv_navigation": {"goal": [1, 2], "speed": 1, "safety_radius": 1, "control_horizon": 1}}}]}),
            "usv_navigation parameters apply only to mode usv_navigation",
        ),
        (_with(execution={"runs": [{"stack": {"mode": "usv_navigation", "usv_navigation": {"goal": [1, 2]}}}]}), "execution.runs.0.stack.usv_navigation.speed: Field required"),
        (_with(execution={"runs": [{"seed": 2**31}]}), "execution.runs.0.seed: Input should be less than or equal to 2147483647"),
        (_with(policy={"seed": -1}), "policy.seed"),
        (_with(policy={"retention": "some"}), "policy.retention: Input should be 'all', 'failures' or 'verdicts_only'"),
        (_with(resources={"queue_depth": {"simulate": 0}}), "resources.queue_depth.simulate"),
        (_with(resources={"nodes": ["node-a", "node-a"]}), "resources.nodes: Value error, node ids must be distinct"),
        (_with(resources={"nodes": ["node-a", " "]}), "resources.nodes: Value error, a node id must not be empty"),
        (_with(domain={"vessel_types": "- just\n- a list\n"}), "domain.vessel_types: Value error, expected a YAML mapping"),
        (_with(domain={"colregs_constants": "a: [unclosed"}), "domain.colregs_constants: Value error, not valid YAML"),
        (_with(domain={"scene_generation_timeout_s": 0}), "domain.scene_generation_timeout_s"),
    ],
)
def test_invalid_configs_are_rejected_with_the_reason(data, reason):
    assert reason in _reasons(data)


def test_every_problem_is_reported():
    reasons = _reasons(_with(scope=[{"classes": ["a/b"], "quota": 0}], policy={"seed": -1}, colour="blue"))
    assert "scope.0.quota" in reasons and "policy.seed" in reasons and "colour" in reasons


@pytest.mark.parametrize(
    "text, reason",
    [
        ("name: a\nname: b\nscope: []\n", "found the key 'name' twice"),
        ("- a\n- b\n", "a campaign config is a mapping of its sections"),
        ("name: [unclosed\n", "not valid YAML"),
        ("name: !!python/object:os.system x\n", "not valid YAML"),
    ],
)
def test_yaml_is_loaded_safely_and_strictly(text, reason):
    assert reason in _reasons(text)


# Hash


def test_the_hash_is_the_sha256_of_canonical_json():
    config = campaign_config_from_dict(MINIMAL)
    assert config.config_hash() == hashlib.sha256(canonical_json(config.to_json()).encode("utf-8")).hexdigest()


def test_the_hash_does_not_depend_on_key_order_or_source():
    from_yaml = load_campaign_config(EXIT_CAMPAIGN)
    reordered = {key: value for key, value in reversed(list(from_yaml.to_json().items()))}
    assert campaign_config_from_dict(reordered).config_hash() == from_yaml.config_hash()
    assert campaign_config_from_dict(from_yaml.to_json()) == from_yaml


def test_the_hash_does_not_depend_on_line_endings():
    lf = campaign_config_from_dict(_with(domain={"colregs_constants": "A: 1\nB: 2\n"}))
    crlf = campaign_config_from_dict(_with(domain={"colregs_constants": "A: 1\r\nB: 2\r\n"}))
    assert crlf.domain.colregs_constants == "A: 1\nB: 2\n"
    assert crlf.config_hash() == lf.config_hash()


def test_the_hash_follows_every_value():
    base = campaign_config_from_dict(MINIMAL)
    changed = [
        _with(scope=[{"classes": ["2vessel_0obstacle_scenarios/functional_model0"], "quota": 3}]),
        _with(policy={"seed": 1}),
        _with(domain={"enforce_low_tcpa": True}),
        _with(execution={"runs": [{"monitor": "empty"}]}),
        _with(description="another"),
    ]
    hashes = {campaign_config_from_dict(data).config_hash() for data in changed}
    assert len(hashes) == len(changed) and base.config_hash() not in hashes


def test_the_hash_is_the_same_in_another_process():
    """No set or dict order of one interpreter leaks into the hash."""
    script = "from scenegems_tool.assurance.campaign import load_campaign_config; import sys; print(load_campaign_config(sys.argv[1]).config_hash())"
    environment = dict(os.environ, PYTHONHASHSEED="12345", PYTHONPATH=str(Path(__file__).resolve().parents[4]))
    other = subprocess.run([sys.executable, "-c", script, str(EXIT_CAMPAIGN)], capture_output=True, text=True, env=environment, check=True).stdout.strip()
    assert other == load_campaign_config(EXIT_CAMPAIGN).config_hash()


# Seeds


def test_case_seeds_are_31_bit_sha256_prefixes():
    expected = int.from_bytes(hashlib.sha256(b"20261025:3vessel_0obstacle_scenarios/functional_model5:7").digest()[:4], "big") & MAX_SEED
    assert case_seed(20261025, "3vessel_0obstacle_scenarios/functional_model5", 7) == expected
    seeds = [case_seed(seed, class_id, index) for seed in (0, 1) for class_id in ("a/b", "a/c") for index in range(50)]
    assert all(0 <= seed <= MAX_SEED for seed in seeds)
    assert len(set(seeds)) == len(seeds)


def test_seeds_are_deterministic():
    config = load_campaign_config(EXIT_CAMPAIGN)
    assert config.case_seed("2vessel_0obstacle_scenarios/functional_model1", 3) == case_seed(20261025, "2vessel_0obstacle_scenarios/functional_model1", 3)
    assert run_seed(123, 0) == run_seed(123, 0) != run_seed(123, 1)
    assert run_seed(123, 0) == int.from_bytes(hashlib.sha256(b"123:run:0").digest()[:4], "big") & MAX_SEED


def test_a_run_seed_is_derived_unless_the_run_fixes_one():
    assert RunConfig().seed_for(555, 2) == run_seed(555, 2)
    assert RunConfig(seed=17).seed_for(555, 2) == 17


def test_indexes_start_at_zero():
    with pytest.raises(ValueError):
        case_seed(0, "a/b", -1)
    with pytest.raises(ValueError):
        run_seed(0, -1)


def test_the_model_is_immutable():
    config = campaign_config_from_dict(MINIMAL)
    with pytest.raises(Exception):
        config.name = "other"
    assert isinstance(config, CampaignConfig)
