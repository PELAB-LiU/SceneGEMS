"""Monitored two-vessel runs for the monitor tests: an own ship heading east and a target that may turn."""

import math
import os
from functools import lru_cache
from typing import List, Tuple

from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel
from utils.colregs_approximations import COLREGSConstraints
from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER

OWN_SHIP = make_vessel(0, True)
TARGET = make_vessel(1, False)
SPEED = 8.0


@lru_cache(maxsize=1)
def constants() -> COLREGSConstraints:
    with open(os.path.join(COLREGS_CONSTANTS_FOLDER, "general_maritime_constants.yaml"), encoding="utf-8") as file:
        return COLREGSConstraints.from_file_content(file.read())


@lru_cache(maxsize=8)
def monitored_run(target_start: Tuple[float, float], steps: int, turn_at: int = -1, turn_s: int = 0) -> List[MonitoredSceneWithResults]:
    """The own ship from the origin heading east, the target from target_start heading north, both at SPEED,
    the target turning to port at 1 degree per second for turn_s seconds from turn_at. One result per second."""
    scenes = []
    target = ActorState(target_start[0], target_start[1], SPEED, math.pi / 2)
    for t in range(steps):
        scenes.append(ConcreteScene({OWN_SHIP: ActorState(SPEED * t, 0.0, SPEED, 0.0), TARGET: target}))
        heading = target.heading + (math.radians(1.0) if turn_at <= t < turn_at + turn_s else 0.0)
        target = ActorState(target.x + SPEED * math.cos(heading), target.y + SPEED * math.sin(heading), SPEED, heading)
    runtime = ColregsMonitorRuntime(constants())
    results: List[MonitoredSceneWithResults] = []
    for index, scene in enumerate(scenes):
        runtime.add_task(MonitoringTask(scene=scene, scene_timestamp=index, time_step=1))
        results.extend(runtime.monitor_current_tasks())
    return results
