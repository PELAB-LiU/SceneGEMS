from typing import Callable

from scenegems_tool.gateway.protocol import ServerMessage, make_error_message
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.workbench.scenario_session import ScenarioSession
from scenegems_tool.workbench.subsystem_integration_session import SubsystemIntegrationSession

NOT_CONNECTED_MESSAGE = "No MQTT broker is connected: connect one on the Connections page"


class EmptySubsystemIntegrationSession(SubsystemIntegrationSession):
    def __init__(self, send_payload: Callable[[ServerMessage], None]):
        super().__init__(send_payload)

    @property
    def is_connected(self) -> bool:
        return False

    def set_monitor_session(self, name: str, topic: str, scope: str, colregs_constraints_content: str) -> None:
        self.send_payload(make_error_message(message=NOT_CONNECTED_MESSAGE))

    def set_simulation_session(self, scenario_session: ScenarioSession, simulation_config: SimulationInstanceConfig) -> None:
        self.send_payload(make_error_message(message=NOT_CONNECTED_MESSAGE))

    def _cancel(self) -> None:
        pass
