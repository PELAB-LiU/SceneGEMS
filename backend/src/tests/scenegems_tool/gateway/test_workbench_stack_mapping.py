"""The workbench vocabulary (simulatorType, controlMode) and the stack triples it maps to."""

import pytest

from scenegems_tool.gateway.workbench_stack_mapping import (
    WORKBENCH_CONTROL_LAYER,
    asv_software_from_control_mode,
    control_mode_label,
    simulation_layer_from_simulator_type,
    simulator_type_label,
    workbench_adapter_ids,
    workbench_stack,
)
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId


class TestSimulatorType:
    @pytest.mark.parametrize("label,layer", [("Gazebo", SimulationLayerId.GAZEBO), ("ArduPilot Sim", SimulationLayerId.ARDUPILOT_SIM)])
    def test_labels_map_to_layers(self, label, layer):
        assert simulation_layer_from_simulator_type(label) == layer
        assert simulator_type_label(layer) == label

    @pytest.mark.parametrize("label", ["gazebo", "GAZEBO", "  Gazebo  ", "ardupilot sim"])
    def test_label_is_case_and_space_insensitive(self, label):
        simulation_layer_from_simulator_type(label)

    def test_unknown_simulator_type_lists_the_choices(self):
        with pytest.raises(ValueError, match="Unknown simulatorType 'Webots'; expected one of Gazebo, ArduPilot Sim"):
            simulation_layer_from_simulator_type("Webots")

    def test_the_kinematic_layer_has_no_workbench_label_yet(self):
        with pytest.raises(ValueError, match="kinematic has no workbench simulatorType"):
            simulator_type_label(SimulationLayerId.KINEMATIC)


class TestControlMode:
    @pytest.mark.parametrize("label,software", [("autonomous", AsvSoftwareId.REPLAY), ("external", AsvSoftwareId.MISSION_PLANNER)])
    def test_modes_map_to_asv_software(self, label, software):
        assert asv_software_from_control_mode(label) == software
        assert control_mode_label(software) == label

    def test_control_mode_is_case_sensitive(self):
        with pytest.raises(ValueError, match="Unknown controlMode 'Autonomous'; expected one of autonomous, external"):
            asv_software_from_control_mode("Autonomous")

    def test_usv_navigation_has_no_workbench_mode_yet(self):
        with pytest.raises(ValueError, match="usv_navigation has no workbench controlMode"):
            control_mode_label(AsvSoftwareId.USV_NAVIGATION)


class TestStackAndAdapters:
    def test_every_workbench_stack_runs_the_ardupilot_control_layer(self):
        assert WORKBENCH_CONTROL_LAYER == ControlLayerId.ARDUPILOT
        stack = workbench_stack("Gazebo", "autonomous")
        assert (stack.asv_software, stack.control_layer, stack.simulation_layer) == (AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO)

    def test_external_control_on_ardupilot_sim(self):
        stack = workbench_stack("ArduPilot Sim", "external")
        assert (stack.asv_software, stack.simulation_layer) == (AsvSoftwareId.MISSION_PLANNER, SimulationLayerId.ARDUPILOT_SIM)

    def test_autonomous_vessels_use_the_arduagent_follower_not_the_registry_default(self):
        assert workbench_adapter_ids("autonomous") == ("replay_arduagent_follower",)

    def test_external_vessels_use_the_registry_default(self):
        assert workbench_adapter_ids("external") == ()

    def test_unknown_control_mode_is_rejected_by_the_adapter_lookup(self):
        with pytest.raises(ValueError, match="Unknown controlMode"):
            workbench_adapter_ids("manual")
