from scenegems_tool.cluster.fingerprints.job_images import (
    GAZEBO_IMAGE,
    JOB_TYPE_IMAGES,
    MONITORING_IMAGE,
    SCENARIO_EXECUTION_IMAGE,
    SCENE_GENERATION_IMAGE,
    SITL_IMAGE,
    TRAJECTORY_GENERATION_IMAGE,
    capability_images,
    job_images,
)
from scenegems_tool.cluster.node.subsystem import Subsystem, subsystem_image
from scenegems_tool.cluster.protocol.jobs import JobType


def test_every_job_type_has_its_images():
    assert set(JOB_TYPE_IMAGES) == set(JobType)


def test_the_subsystem_images_are_the_ones_the_node_launches(monkeypatch):
    for variable in ("SCENARIO_GENERATION_IMAGE", "TRAJECTORY_GENERATION_IMAGE", "MONITORING_IMAGE", "SCENARIO_EXECUTION_IMAGE"):
        monkeypatch.delenv(variable, raising=False)
    assert subsystem_image(Subsystem.SCENE_GENERATION) == SCENE_GENERATION_IMAGE
    assert subsystem_image(Subsystem.TRAJECTORY_GENERATION) == TRAJECTORY_GENERATION_IMAGE
    assert subsystem_image(Subsystem.MONITORING) == MONITORING_IMAGE
    assert subsystem_image(Subsystem.SCENARIO_EXECUTION) == SCENARIO_EXECUTION_IMAGE


def test_the_simulator_images_are_the_ones_the_stacks_use():
    from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_specs import SITL_CONTAINER
    from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import GAZEBO_CONTAINER

    assert SITL_IMAGE in SITL_CONTAINER.image and GAZEBO_IMAGE in GAZEBO_CONTAINER.image


def test_an_ardupilot_job_needs_gazebo_only_on_the_gazebo_layer():
    assert job_images(JobType.SIMULATION_ARDUPILOT, {"simulation_layer": "ardupilot_sim"}) == (SCENARIO_EXECUTION_IMAGE, SITL_IMAGE)
    assert job_images(JobType.SIMULATION_ARDUPILOT, {"simulation_layer": "gazebo"}) == (SCENARIO_EXECUTION_IMAGE, SITL_IMAGE, GAZEBO_IMAGE)
    assert job_images(JobType.SCENE_GENERATION, {"simulation_layer": "gazebo"}) == (SCENE_GENERATION_IMAGE,)


def test_capability_images():
    assert capability_images([JobType.SIMULATION_KINEMATIC, JobType.MONITORING_POST_HOC]) == {SCENARIO_EXECUTION_IMAGE, MONITORING_IMAGE}
    assert capability_images([]) == set()
