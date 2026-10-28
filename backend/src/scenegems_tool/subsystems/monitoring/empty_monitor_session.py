from typing import Callable, Sequence

from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.gateway.protocol import ServerMessage
from scenegems_tool.subsystems.monitoring.monitor_session import MonitorSession


class EmptyMonitorSession(MonitorSession):
    def __init__(self, send_payload: Callable[[ServerMessage], None]):
        super().__init__(send_payload)

    def step_preview_monitor_batch(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
    ) -> None:
        self.send_unmonitored_chunk(scenario_id, scenes, timestamps, time_step, is_simulation_frame=False)

    def step_simulation_monitor_batch(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
    ) -> None:
        self.send_unmonitored_chunk(scenario_id, scenes, timestamps, time_step, is_simulation_frame=True)

    @property
    def is_connected(self) -> bool:
        return False

    def _destroy(self) -> None:
        pass
