"""The images each job type runs in, named as deploy/scripts/build.sh tags and lists them.

The master requires these images' fingerprints of a job (JobRequirements.fingerprints) and
of a node before it leases to it; a node checks the same list to know what to rebuild.
"""

from typing import Any, Collection, Mapping, Set, Tuple

from scenegems_tool.cluster.protocol.jobs import JobType

SCENE_GENERATION_IMAGE = "scenegems-scenario-generation-subsystem:latest"
TRAJECTORY_GENERATION_IMAGE = "scenegems-trajectory-generation-subsystem:latest"
SCENARIO_EXECUTION_IMAGE = "scenegems-scenario-execution-subsystem:latest"
MONITORING_IMAGE = "scenegems-monitoring-subsystem:latest"
SITL_IMAGE = "scenegems-ardupilot-sitl:latest"
GAZEBO_IMAGE = "scenegems-gazebo-harmonic:latest"

# Images every job of a type needs. A simulation.ardupilot job on the Gazebo layer needs
# Gazebo as well (job_images), which only that job requires, not every simulation node.
JOB_TYPE_IMAGES = {
    JobType.SCENE_GENERATION: (SCENE_GENERATION_IMAGE,),
    JobType.TRAJECTORY_GENERATION: (TRAJECTORY_GENERATION_IMAGE,),
    JobType.SIMULATION_KINEMATIC: (SCENARIO_EXECUTION_IMAGE,),
    JobType.SIMULATION_ARDUPILOT: (SCENARIO_EXECUTION_IMAGE, SITL_IMAGE),
    JobType.MONITORING_POST_HOC: (MONITORING_IMAGE,),
    JobType.CALIBRATION_DEVIATION: (SCENARIO_EXECUTION_IMAGE,),
}
GAZEBO_LAYER = "gazebo"  # the simulation_layer of an ArduPilot payload that runs a Gazebo world


def job_images(job_type: JobType, payload: Mapping[str, Any]) -> Tuple[str, ...]:
    """The images one job runs in, read from its type and, for ArduPilot jobs, its simulation layer."""
    images = JOB_TYPE_IMAGES[job_type]
    if job_type == JobType.SIMULATION_ARDUPILOT and payload.get("simulation_layer") == GAZEBO_LAYER:
        images = images + (GAZEBO_IMAGE,)
    return images


def capability_images(job_types: Collection[JobType]) -> Set[str]:
    """The images a node that offers these job types must have built."""
    return {image for job_type in job_types for image in JOB_TYPE_IMAGES[job_type]}
