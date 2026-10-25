"""The availability matrix: all 27 (ASV software, control layer, simulation layer) triples against design section 3.3."""

from typing import Dict, List, Tuple

import pytest

from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig
from scenegems_tool.vessel_stack.registry.catalog import default_resolver

AVAILABLE = "available"
PLANNED = "planned (phase 2)"
UNAVAILABLE = "unavailable"

RULED_OUT = {
    "mission_planner_none": "control layer none has no MAVLink endpoint",
    "mission_planner_custom": "the custom controller has no MAVLink",
    "none_gazebo": "Gazebo needs actuator commands",
    "none_ardupilot_sim": "ardupilot_sim is the physics inside ArduPilot SITL",
    "custom_ardupilot_sim": "SITL physics only accepts ArduPilot control",
    "kinematic": "the kinematic sim integrates control internally",
}

# (asv, control, simulation): (design status of section 3.3, status now, text every reason must contain)
# Design status "yes" rows are available now or planned for Phase 2; the "no" rows are unavailable
# with the design's reason. none with ardupilot_sim is a "no" added in Phase 1 (design doc 11.2).
EXPECTED: Dict[Tuple[str, str, str], Tuple[str, str, List[str]]] = {
    ("replay", "none", "kinematic"): ("yes", AVAILABLE, []),
    ("replay", "ardupilot", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["kinematic"]]),
    ("replay", "custom", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["kinematic"]]),
    ("replay", "ardupilot", "ardupilot_sim"): ("yes", AVAILABLE, []),
    ("replay", "none", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["none_ardupilot_sim"]]),
    ("replay", "custom", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["custom_ardupilot_sim"]]),
    ("replay", "ardupilot", "gazebo"): ("yes", AVAILABLE, []),
    ("replay", "custom", "gazebo"): ("yes", PLANNED, ["custom_controller_waypoint_follower is planned", "gz_transport_actuator is planned"]),
    ("replay", "none", "gazebo"): ("no", UNAVAILABLE, [RULED_OUT["none_gazebo"]]),
    ("usv_navigation", "none", "kinematic"): ("yes", AVAILABLE, []),
    ("usv_navigation", "ardupilot", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["kinematic"]]),
    ("usv_navigation", "custom", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["kinematic"]]),
    ("usv_navigation", "ardupilot", "ardupilot_sim"): ("yes", PLANNED, ["usv_navigation_mavlink_guided is planned"]),
    ("usv_navigation", "none", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["none_ardupilot_sim"]]),
    ("usv_navigation", "custom", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["custom_ardupilot_sim"]]),
    ("usv_navigation", "ardupilot", "gazebo"): ("yes", PLANNED, ["usv_navigation_mavlink_guided is planned"]),
    ("usv_navigation", "custom", "gazebo"): ("yes", PLANNED, ["custom_controller_heading_speed_input is planned", "gz_transport_actuator is planned"]),
    ("usv_navigation", "none", "gazebo"): ("no", UNAVAILABLE, [RULED_OUT["none_gazebo"]]),
    ("mission_planner", "none", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_none"]]),
    ("mission_planner", "ardupilot", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["kinematic"]]),
    ("mission_planner", "custom", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_custom"], RULED_OUT["kinematic"]]),
    ("mission_planner", "ardupilot", "ardupilot_sim"): ("yes, interactive only", AVAILABLE, []),
    ("mission_planner", "none", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_none"], RULED_OUT["none_ardupilot_sim"]]),
    ("mission_planner", "custom", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_custom"], RULED_OUT["custom_ardupilot_sim"]]),
    ("mission_planner", "ardupilot", "gazebo"): ("yes, interactive only", AVAILABLE, []),
    ("mission_planner", "custom", "gazebo"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_custom"]]),
    ("mission_planner", "none", "gazebo"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_none"], RULED_OUT["none_gazebo"]]),
}


def triple(chain) -> Tuple[str, str, str]:
    return (chain.stack.asv_software.value, chain.stack.control_layer.value, chain.stack.simulation_layer.value)


@pytest.fixture(scope="module")
def matrix():
    return {triple(chain): chain for chain in default_resolver().availability_matrix()}


def test_expected_table_covers_every_role_combination():
    every_triple = {(asv.value, control.value, simulation.value) for asv in AsvSoftwareId for control in ControlLayerId for simulation in SimulationLayerId}
    assert len(every_triple) == 27
    assert set(EXPECTED) == every_triple


def test_availability_matrix_lists_each_triple_once():
    chains = default_resolver().availability_matrix()
    assert len(chains) == 27
    assert len({triple(chain) for chain in chains}) == 27


def test_availability_matrix_orders_by_asv_then_simulation_then_control():
    chains = default_resolver().availability_matrix()
    assert [triple(chain) for chain in chains[:3]] == [("replay", "ardupilot", "kinematic"), ("replay", "custom", "kinematic"), ("replay", "none", "kinematic")]
    assert [chain.stack.simulation_layer for chain in chains[:9]].count(SimulationLayerId.KINEMATIC) == 3


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_triple_matches_design_table(matrix, key):
    design_status, status, reason_parts = EXPECTED[key]
    chain = matrix[key]
    assert chain.design_status == design_status
    assert chain.status == status
    assert chain.available == (status == AVAILABLE)
    for part in reason_parts:
        assert part in chain.reason
    if status == AVAILABLE:
        assert chain.reasons == ()


def test_matrix_counts_are_six_available_four_planned_seventeen_unavailable(matrix):
    statuses = [chain.status for chain in matrix.values()]
    assert statuses.count(AVAILABLE) == 6
    assert statuses.count(PLANNED) == 4
    assert statuses.count(UNAVAILABLE) == 17


def test_design_yes_rows_are_exactly_the_complete_chains(matrix):
    for chain in matrix.values():
        assert chain.complete == (chain.design_status != "no")


def test_unavailable_chain_has_no_capabilities(matrix):
    chain = matrix[("replay", "none", "gazebo")]
    assert chain.capabilities is None
    assert not chain.complete


def test_every_unavailable_row_names_a_reason(matrix):
    for chain in matrix.values():
        if not chain.available:
            assert chain.reason
            assert chain.reasons


def test_available_replay_on_ardupilot_defaults_to_the_lockstep_link(matrix):
    for simulation in ("ardupilot_sim", "gazebo"):
        chain = matrix[("replay", "ardupilot", simulation)]
        assert chain.asv_adapter is not None
        assert chain.asv_adapter.id == "replay_mavlink_lockstep"


def test_mission_planner_rows_are_interactive_only(matrix):
    for simulation in ("ardupilot_sim", "gazebo"):
        capabilities = matrix[("mission_planner", "ardupilot", simulation)].capabilities
        assert capabilities.interactive_only
        assert not capabilities.lockstep


def test_planned_chain_lists_the_planned_specs(matrix):
    chain = matrix[("usv_navigation", "custom", "gazebo")]
    planned_ids = {spec.id for spec in chain.planned_specs}
    assert planned_ids == {"control_layer/custom", "custom_controller_heading_speed_input", "gz_transport_actuator"}


def test_resolving_with_an_adapter_alternative_changes_the_asv_adapter():
    stack = VesselStackConfig(AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM)
    chain = default_resolver().resolve(stack, ["replay_arduagent_follower"])
    assert chain.available
    assert chain.asv_adapter.id == "replay_arduagent_follower"
    assert chain.capabilities.lockstep is False
    assert chain.capabilities.exact_up_to_speedup == 1


def test_unknown_adapter_id_is_a_reason():
    stack = VesselStackConfig(AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM)
    chain = default_resolver().resolve(stack, ["no_such_adapter"])
    assert not chain.available
    assert "adapter no_such_adapter is not registered" in chain.reason


def test_adapter_of_another_connection_is_a_reason():
    stack = VesselStackConfig(AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM)
    chain = default_resolver().resolve(stack, ["kinematic_command_input"])
    assert not chain.available
    assert "kinematic_command_input connects control_layer/none to simulation_layer/kinematic, which is not part of" in chain.reason
