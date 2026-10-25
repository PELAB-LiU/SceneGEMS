"""The module of each job type. Every module defines its payload model and `run`; the ones
that run in a per-job runner container also define `execute`, their in-container part."""

from types import ModuleType
from typing import Dict

from scenegems_tool.cluster.node.jobs import (
    monitoring_post_hoc_job,
    scene_generation_job,
    simulation_ardupilot_job,
    simulation_kinematic_job,
    trajectory_generation_job,
)
from scenegems_tool.cluster.protocol.jobs import JobType

JOB_TYPE_MODULES: Dict[JobType, ModuleType] = {
    JobType.SCENE_GENERATION: scene_generation_job,
    JobType.TRAJECTORY_GENERATION: trajectory_generation_job,
    JobType.SIMULATION_KINEMATIC: simulation_kinematic_job,
    JobType.SIMULATION_ARDUPILOT: simulation_ardupilot_job,
    JobType.MONITORING_POST_HOC: monitoring_post_hoc_job,
}


def job_type_module(job_type: JobType) -> ModuleType:
    return JOB_TYPE_MODULES[job_type]
