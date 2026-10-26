"""CustomControlLayer: the controller runs in the runner, so a vessel adds nothing to the Docker stack."""

import pytest

from scenegems_tool.vessel_stack.contracts.docker_stack import DockerControlLayer, DockerStackArtifacts
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.control_layers.custom.custom_control_layer import CustomControlLayer
from tests.scenegems_tool.vessel_stack.scenarios import stack_instance, straight_trajectories


def test_it_is_a_docker_control_layer():
    assert isinstance(CustomControlLayer(), DockerControlLayer)


def test_a_custom_vessel_adds_no_file_and_no_service():
    instance = stack_instance(SimulationLayerId.GAZEBO, [0], control_layer=ControlLayerId.CUSTOM)
    trajectories = straight_trajectories()
    vessel = trajectories.initial_scene.vessels[0]
    artifacts = DockerStackArtifacts()
    CustomControlLayer().add_vessel(artifacts, None, instance.vessels["0"], vessel, trajectories.initial_scene[vessel])
    assert artifacts.pending_writes == [] and artifacts.services == {}


def test_it_drives_gazebo_only():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], control_layer=ControlLayerId.CUSTOM)
    trajectories = straight_trajectories()
    vessel = trajectories.initial_scene.vessels[0]
    with pytest.raises(ValueError, match="Gazebo only"):
        CustomControlLayer().add_vessel(DockerStackArtifacts(), None, instance.vessels["0"], vessel, trajectories.initial_scene[vessel])
