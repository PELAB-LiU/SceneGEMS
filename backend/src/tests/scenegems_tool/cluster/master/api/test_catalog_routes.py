"""The catalog routes: the classes a campaign draws from and the stacks, monitors and generators a run may use. No database needed."""

import json

import pytest
from starlette.testclient import TestClient

from scenegems_tool.assurance.campaign import ClassCatalog
from scenegems_tool.assurance.campaign.campaign_config import SEARCH_PARAM_KEYS, KinematicStackConfig, RunConfig, TrajectoriesConfig, parse_campaign_config
from scenegems_tool.assurance.campaign.config_validation import validate_campaign_config
from scenegems_tool.cluster.master.api.master_apps import create_operator_app
from scenegems_tool.cluster.node.jobs.simulation_kinematic_job import KinematicMode, UsvNavigationPayload
from scenegems_tool.cluster.protocol.routes import CATALOG_PATH
from scenegems_tool.persistence.schema import MonitorImplementation, TrajectoryGeneratorImplementation
from scenegems_tool.vessel_stack.registry.catalog import default_resolver

CLASSES = f"{CATALOG_PATH}/classes"
STACKS = f"{CATALOG_PATH}/stacks"


@pytest.fixture
def operator(memory_plane):
    with TestClient(create_operator_app(memory_plane)) as client:  # no campaign stores: the catalog needs none
        yield client


@pytest.fixture
def small_catalog(tmp_path, monkeypatch):
    """Four classes in two folders, in a folder of their own."""
    problems = {
        "2vessel_0obstacle_scenarios/functional_model1": "OS(os1).\nTS(ts1).\n",
        "2vessel_0obstacle_scenarios/functional_model2": "OS(os1).\nTS(ts1).\n\nr(os1, ts1).\n",
        "2vessel_0obstacle_scenarios/functional_model10": "OS(os1).\nTS(ts1).\n",
        "3vessel_1obstacle_scenarios/functional_model1": "OS(os1).\nTS(ts1).\nTS(ts2).\nStaticObstacle(o1).\n",
    }
    for class_id, content in problems.items():
        path = tmp_path / f"{class_id}.problem"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))  # a Windows checkout
    catalog = ClassCatalog(tmp_path)
    monkeypatch.setattr(ClassCatalog, "default", classmethod(lambda cls: catalog))
    return catalog


def test_the_classes_are_the_catalogs_with_their_counts_and_hashes(operator, small_catalog):
    response = operator.get(CLASSES)
    assert response.status_code == 200 and response.headers["x-total-count"] == "4"
    classes = response.json()
    assert [entry["class_id"] for entry in classes] == [
        "2vessel_0obstacle_scenarios/functional_model1",
        "2vessel_0obstacle_scenarios/functional_model2",
        "2vessel_0obstacle_scenarios/functional_model10",  # numbers in numeric order
        "3vessel_1obstacle_scenarios/functional_model1",
    ]
    last = classes[-1]
    assert last == {
        "class_id": "3vessel_1obstacle_scenarios/functional_model1",
        "folder": "3vessel_1obstacle_scenarios",
        "vessel_count": 3,
        "obstacle_count": 1,
        "content_hash": small_catalog.get(last["class_id"]).content_hash,
    }
    assert len(last["content_hash"]) == 64 and classes[0]["content_hash"] == classes[2]["content_hash"]  # the same content, the same hash, whatever the line endings


def test_the_classes_can_be_filtered_by_folder_and_pattern(operator, small_catalog):
    def ids(**params):
        response = operator.get(CLASSES, params=params)
        return [entry["class_id"] for entry in response.json()], int(response.headers["x-total-count"])

    assert ids(folder="3vessel_1obstacle_scenarios") == (["3vessel_1obstacle_scenarios/functional_model1"], 1)
    assert ids(folder="nothing")[1] == 0
    assert ids(pattern="3vessel_*")[1] == 1  # a pattern without a slash matches folders
    assert ids(pattern="*/functional_model1")[0] == ["2vessel_0obstacle_scenarios/functional_model1", "3vessel_1obstacle_scenarios/functional_model1"]  # one with a slash, class ids
    assert ids(pattern="2vessel_*/functional_model1*")[1] == 2
    assert ids(pattern="*/functional_model1", folder="2vessel_0obstacle_scenarios") == (["2vessel_0obstacle_scenarios/functional_model1"], 1)  # both narrow
    assert ids(pattern="9vessel_*")[1] == 0


def test_the_classes_are_paged_and_the_total_stays(operator, small_catalog):
    second = operator.get(CLASSES, params={"limit": 2, "offset": 1})
    assert [entry["class_id"] for entry in second.json()] == ["2vessel_0obstacle_scenarios/functional_model2", "2vessel_0obstacle_scenarios/functional_model10"]
    assert second.headers["x-total-count"] == "4"
    assert operator.get(CLASSES, params={"offset": 10}).json() == []
    assert len(operator.get(CLASSES, params={"limit": 0}).json()) == 1  # at least one, like the other lists


def test_a_master_without_the_catalog_folder_answers_503(operator, tmp_path, monkeypatch):
    missing = ClassCatalog(tmp_path / "nowhere")
    monkeypatch.setattr(ClassCatalog, "default", classmethod(lambda cls: missing))
    response = operator.get(CLASSES)
    assert response.status_code == 503 and "nowhere" in response.json()["detail"]


def test_the_real_catalog_is_served_in_full(operator):
    catalog = ClassCatalog.default()
    response = operator.get(CLASSES, params={"limit": 1000})
    assert int(response.headers["x-total-count"]) == len(catalog) == len(response.json())
    first = response.json()[0]
    scenario_class = catalog.classes()[0]
    assert (first["class_id"], first["content_hash"], first["vessel_count"]) == (scenario_class.class_id, scenario_class.content_hash, scenario_class.vessel_count)
    assert {entry["folder"] for entry in response.json()} == set(catalog.folders())


# Stacks


@pytest.fixture
def stacks(operator) -> dict:
    response = operator.get(STACKS)
    assert response.status_code == 200
    return response.json()


def by_id(entries, key="id"):
    return {entry[key]: entry for entry in entries}


def test_the_stack_options_are_the_ones_the_campaign_config_accepts(stacks):
    options = by_id(stacks["stacks"])
    assert set(options) == {f"kinematic.{mode.value}" for mode in KinematicMode}
    for mode in KinematicMode:
        option = options[f"kinematic.{mode.value}"]
        assert option["simulation_layer"] == "kinematic" and option["mode"] == mode.value
        assert option["available"] is True and option["reasons"] == []
        assert option["repeatability_tier"] == "exact"
        assert {parameter["key"] for parameter in option["parameters"]} == {"dt", "steps"} <= set(KinematicStackConfig.model_fields)
        assert option["environment"] == {"wind": "unsupported", "waves": "unsupported", "interactive_only": False}


def test_the_vessel_triples_of_a_stack_are_the_resolvers(stacks):
    options = by_id(stacks["stacks"])
    replay = {"asv_software": "replay", "control_layer": "none", "simulation_layer": "kinematic"}
    assert options["kinematic.replay"]["vessels"] == {"own_ship": replay, "target_ship": replay}
    assert options["kinematic.usv_navigation"]["vessels"] == {"own_ship": {**replay, "asv_software": "usv_navigation"}, "target_ship": replay}


def test_usv_navigation_has_its_parameters_with_their_defaults(stacks):
    option = by_id(stacks["stacks"])["kinematic.usv_navigation"]
    assert by_id(by_id(stacks["stacks"])["kinematic.replay"]["groups"], "key") == {}
    (group,) = option["groups"]
    assert group["key"] == "usv_navigation" and group["optional"] is True and "derived_when_absent" in group
    parameters = by_id(group["parameters"], "key")
    assert set(parameters) == set(UsvNavigationPayload.model_fields)
    assert parameters["prescribed_time"]["default"] == UsvNavigationPayload.model_fields["prescribed_time"].default == 3.0
    assert parameters["runtime_options"]["default"] == {}
    assert {key for key, parameter in parameters.items() if parameter["required"]} == {"goal", "speed", "safety_radius", "control_horizon"}
    assert parameters["speed"]["unit"] == "m/s" and parameters["speed"]["exclusive_minimum"] == 0.0 and parameters["goal"]["type"] == "number_pair"


def test_the_monitors_are_the_ones_a_run_names(stacks):
    monitors = by_id(stacks["monitors"])
    assert set(monitors) == {monitor.value for monitor in MonitorImplementation}
    assert {name for name, monitor in monitors.items() if monitor["supports_early_stop"]} == {"live"}
    assert monitors["post_hoc"]["job_types"] == ["monitoring.post_hoc"] and monitors["empty"]["job_types"] == []
    assert all(monitor["label"] and monitor["description"] for monitor in monitors.values())


def test_the_trajectory_generators_list_their_parameters_by_wire_key_with_the_search_defaults(stacks):
    generators = by_id(stacks["trajectory_generators"])
    assert set(generators) == {generator.value for generator in TrajectoryGeneratorImplementation}
    rrt = generators["monitor_driven_rrt"]
    parameters = by_id(rrt["parameters"], "key")
    assert set(parameters) == set(SEARCH_PARAM_KEYS) and rrt["params_field"] == "params"
    from concrete_level.trajectory_generation.monitor_driven_rrt_search import MonitorDrivenRRTSearch

    assert parameters["goalSampleRate"]["default"] == MonitorDrivenRRTSearch.GOAL_SAMPLE_RATE == 50
    assert parameters["maxLeafs"]["default"] == MonitorDrivenRRTSearch.MAX_LEAFS
    assert parameters["timeStep"]["default"] == 15 and parameters["includeMonitorResults"]["default"] is True
    assert parameters["timeout"]["default"] is None and parameters["maxIterations"]["default"] is None
    straight = generators["straight"]
    assert [(parameter["key"], parameter["required"], parameter["unit"]) for parameter in straight["parameters"]] == [("timespan_s", True, "s")]
    assert straight["params_field"] is None
    for generator in generators.values():
        assert {parameter["key"]: parameter["default"] for parameter in generator["common_parameters"]} == {"timeout_s": TrajectoriesConfig.model_fields["timeout_s"].default}


def test_the_run_fields_name_the_defaults_of_the_run_config(stacks):
    fields = by_id(stacks["run_parameters"], "key")
    assert fields["repeats"]["default"] == RunConfig.model_fields["repeats"].default == 1
    assert fields["early_stop"]["default"] is False
    assert {"name", "seed", "repeats", "early_stop", "environment.wind_vector", "environment.waves"} == set(fields)


def test_every_other_stack_of_the_resolver_is_listed_as_unavailable_with_its_reasons(stacks):
    resolver = default_resolver()
    matrix = resolver.availability_matrix()
    unavailable = stacks["unavailable_stacks"]
    offered = {("replay", "none", "kinematic"), ("usv_navigation", "none", "kinematic")}
    listed = {(entry["asv_software"], entry["control_layer"], entry["simulation_layer"]) for entry in unavailable}
    assert len(unavailable) == len(listed) == len(matrix) - len(offered)
    assert not listed & offered
    assert all(entry["reasons"] and all(isinstance(reason, str) and reason for reason in entry["reasons"]) for entry in unavailable)
    assert stacks["resolver"] == {"combinations": len(matrix), "available": sum(1 for chain in matrix if chain.available)}


def test_the_reasons_tell_why_a_resolver_stack_is_not_a_campaign_stack(stacks):
    entries = {(entry["asv_software"], entry["control_layer"], entry["simulation_layer"]): entry for entry in stacks["unavailable_stacks"]}
    gazebo = entries[("replay", "ardupilot", "gazebo")]  # the resolver has it, the campaign config does not offer it yet
    assert gazebo["available_in_resolver"] is True and gazebo["tier"] == "bounded" and "kinematic" in gazebo["reasons"][0]
    usv_navigation = entries[("usv_navigation", "ardupilot", "ardupilot_sim")]  # available since WP5b, not offered to campaigns
    assert usv_navigation["available_in_resolver"] is True and "kinematic" in usv_navigation["reasons"][0]
    impossible = entries[("replay", "ardupilot", "kinematic")]
    assert impossible["status"] == "unavailable" and impossible["design_status"] == "no" and "integrates control internally" in impossible["reasons"][0]
    interactive = entries[("mission_planner", "ardupilot", "gazebo")]
    assert interactive["available_in_resolver"] is True and "interactive only" in interactive["reasons"][0] and interactive["design_status"] == "yes, interactive only"


def test_the_stacks_view_is_plain_json(stacks):
    assert json.loads(json.dumps(stacks, allow_nan=False)) == stacks  # no infinity or NaN from the capabilities


def test_every_offered_stack_is_a_config_the_validation_accepts(stacks):
    for option in stacks["stacks"]:
        text = f"name: probe\nscope:\n  - classes: [2vessel_0obstacle_scenarios/functional_model0]\n    quota: 1\nexecution:\n  runs:\n    - stack: {{simulation_layer: {option['simulation_layer']}, mode: {option['mode']}}}\n"
        validated = validate_campaign_config(parse_campaign_config(text))
        assert validated.runs[0].repeatability_tier == option["repeatability_tier"]
