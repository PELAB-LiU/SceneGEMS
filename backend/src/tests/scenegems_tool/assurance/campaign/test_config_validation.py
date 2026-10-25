from pathlib import Path

import pytest

from scenegems_tool.assurance.campaign import CampaignConfigRejected, ClassCatalog, campaign_config_from_dict, load_campaign_config, validate_campaign_config
from scenegems_tool.assurance.campaign.config_validation import OWN_SHIP, TARGET_SHIP, vessel_stacks
from scenegems_tool.cluster.node.jobs.simulation_kinematic_job import KinematicMode
from scenegems_tool.persistence.stores import AssuranceStores, ClassSpec
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry
from scenegems_tool.vessel_stack.registry.resolver import StackResolver

EXIT_CAMPAIGN = Path(__file__).parent / "data" / "exit_campaign.yaml"
CLASS = "2vessel_0obstacle_scenarios/functional_model0"


def _config(scope=None, **sections):
    return campaign_config_from_dict(dict({"name": "lab", "scope": scope or [{"classes": [CLASS], "quota": 2, "failure_budget": 1}]}, **sections))


def _rejection(config, **arguments) -> str:
    with pytest.raises(CampaignConfigRejected) as rejected:
        validate_campaign_config(config, **arguments)
    return "\n".join(rejected.value.reasons)


def test_the_exit_campaign_has_70_classes_and_1050_cases():
    validated = validate_campaign_config(load_campaign_config(EXIT_CAMPAIGN))
    assert len(validated.classes) == 70 and validated.total_quota == 1050
    assert {(spec.quota, spec.failure_budget) for spec in validated.classes} == {(15, 15)}
    assert {spec.vessel_count for spec in validated.classes} == {2, 3}
    catalog = ClassCatalog.default()
    assert all(spec.content_hash == catalog.get(spec.class_id).content_hash for spec in validated.classes)
    assert [spec.class_id for spec in validated.classes[:2]] == ["2vessel_0obstacle_scenarios/functional_model0", "2vessel_0obstacle_scenarios/functional_model1"]
    (run,) = validated.runs
    assert run.vessels[OWN_SHIP].asv_software == AsvSoftwareId.USV_NAVIGATION and run.vessels[TARGET_SHIP].asv_software == AsvSoftwareId.REPLAY
    assert (run.repeatability_tier, run.environment, run.warnings) == ("exact", {"wind_vector": None, "waves": None}, ())
    assert validated.config_hash == validated.config.config_hash() and validated.config_json == validated.config.to_json()


def test_classes_come_as_the_store_takes_them():
    (spec,) = validate_campaign_config(_config()).classes
    assert spec == ClassSpec(class_id=CLASS, content_hash=ClassCatalog.default().get(CLASS).content_hash, vessel_count=2, obstacle_count=0, quota=2, failure_budget=1)


def test_a_class_named_twice_in_one_entry_counts_once():
    validated = validate_campaign_config(_config([{"classes": [CLASS], "patterns": ["2vessel_0obstacle_scenarios"], "quota": 1}]))
    assert [spec.class_id for spec in validated.classes] == [f"2vessel_0obstacle_scenarios/functional_model{index}" for index in range(7)]


def test_unknown_classes_and_empty_patterns_are_rejected_together():
    reasons = _rejection(
        _config(
            [
                {"classes": [CLASS, "2vessel_0obstacle_scenarios/functional_model99"], "quota": 1},
                {"patterns": ["9vessel_*"], "quota": 1},
                {"patterns": ["2vessel_0obstacle_scenarios"], "quota": 3},
            ]
        )
    )
    assert "scope.0: no class '2vessel_0obstacle_scenarios/functional_model99' in the catalog" in reasons
    assert "scope.1: the pattern '9vessel_*' matches no class" in reasons
    assert f"scope.2: class '{CLASS}' is in scope.0 already" in reasons


def test_the_resolver_refuses_wind_on_the_kinematic_layer():
    reasons = _rejection(_config(execution={"runs": [{"name": "windy", "environment": {"wind_vector": [3.0, 0.0, 0.0]}}]}))
    assert "execution.runs.0 (windy): wind requested, but simulation_layer/kinematic does not support wind" in reasons


def test_the_resolver_refuses_waves_on_the_kinematic_layer():
    waves = {"amplitude": 0.5, "period": 4.0, "steepness": 0.1, "direction": [1.0, 0.0]}
    assert "waves requested, but simulation_layer/kinematic does not support waves" in _rejection(_config(execution={"runs": [{}, {"environment": {"waves": waves}}]}))


def test_a_stack_the_resolver_does_not_know_is_refused():
    reasons = _rejection(_config(execution={"runs": [{"stack": {"mode": "usv_navigation"}}]}), resolver=StackResolver(AdapterRegistry()))
    assert "execution.runs.0: vessel own_ship (usv_navigation, none, kinematic): asv_software/usv_navigation is not registered" in reasons


def test_vessel_stacks_per_mode():
    replay = _config().execution.runs[0].stack
    assert {stack.asv_software for stack in vessel_stacks(replay).values()} == {AsvSoftwareId.REPLAY}
    closed_loop = _config(execution={"runs": [{"stack": {"mode": "usv_navigation"}}]}).execution.runs[0].stack
    assert closed_loop.mode == KinematicMode.USV_NAVIGATION
    assert vessel_stacks(closed_loop)[OWN_SHIP].asv_software == AsvSoftwareId.USV_NAVIGATION


@pytest.mark.postgres
def test_a_validated_campaign_is_stored_and_read_back_to_the_same_hash(session_factory):
    validated = validate_campaign_config(load_campaign_config(EXIT_CAMPAIGN))
    stores = AssuranceStores.create(session_factory)
    campaign = stores.campaigns.create_campaign(validated.config.name, validated.config_json, validated.config_hash, validated.classes)
    stored = stores.campaigns.config_version(campaign.campaign_id)
    assert stored.config_hash == validated.config_hash
    assert campaign_config_from_dict(stored.config).config_hash() == validated.config_hash
    classes = stores.cases.list_classes(campaign.campaign_id)
    assert len(classes) == 70 and sum(item.quota for item in classes) == 1050
