import asyncio
import json
from datetime import datetime, timezone
from typing import Union

from fastapi import WebSocket

from concrete_level.trajectory_generation.trajectory_data import TrajectoryData
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.workbench.empty_scenario_session import EmptyScenarioSession
from scenegems_tool.workbench.live_scenario_session import LiveScenarioSession
from scenegems_tool.gateway.protocol import ClientMessage, ServerMessage, make_error_message, make_monitor_status_message, make_waraps_status_message
from scenegems_tool.workbench.scenario_session import ScenarioSession
from scenegems_tool.vessel_stack.contracts.simulation_config import SimulationConfig
from scenegems_tool.workbench.empty_subsystem_integration_session import EmptySubsystemIntegrationSession
from scenegems_tool.workbench.live_subsystem_integration_session import LiveSubsystemIntegrationSession
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo, resolve_mqtt_broker_endpoints
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence
from scenegems_tool.workbench.subsystem_integration_session import SubsystemIntegrationSession


class SocketSession:

    def __init__(self, websocket: WebSocket):
        self.websocket: WebSocket = websocket

        self.outbound_queue: asyncio.Queue[ServerMessage] = asyncio.Queue()
        self.outbound_task: asyncio.Task[None] = asyncio.create_task(self._outbound_loop())
        self.waraps_connection_task: asyncio.Task[None] = asyncio.create_task(self._waraps_connection_loop())

        self.created_at_utc = datetime.now(timezone.utc).isoformat()
        self.subsystem_integration_session: SubsystemIntegrationSession = EmptySubsystemIntegrationSession(send_payload=self.send_payload)
        self.scenario_session: ScenarioSession = EmptyScenarioSession(monitor_session=self.subsystem_integration_session.monitor_session, send_payload=self.send_payload)

    @property
    def connection_id(self) -> str:
        return str(id(self.websocket))

    async def _waraps_connection_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            if self.subsystem_integration_session.is_connected:
                status = "connected"
            else:
                status = "disconnected"
            self.send_payload(make_waraps_status_message(status=status))

    def log_payload(self, direction: str, payload: Union[ServerMessage, ClientMessage]) -> None:
        if payload["type"] == "preview_trajectory_chunk" or payload["type"] == "simulation_trajectory_chunk":
            return
        if "status" in payload["type"]:
            return
        print(f"[ws][{direction}] session_id={self.connection_id} type={payload.get('type')}")

    async def _send_payload(self, payload: ServerMessage) -> None:
        self.log_payload("outgoing", payload=payload)
        await self.websocket.send_json(payload)

    async def _outbound_loop(self):
        while True:
            payload = await self.outbound_queue.get()
            await self._send_payload(payload)

    def send_payload(self, payload: ServerMessage) -> None:
        self.outbound_queue.put_nowait(payload)

    def send_runtime_error(self, message: str) -> None:
        self.send_payload(make_error_message(message=message))

    async def connect_to_waraps(self, user: str, password: str, agent_broker: str, client_broker: str, port: int, tls_connection: bool, allow_certificates: bool, reference_geofence: Geofence):
        requested_broker = client_broker.strip()
        agent_broker, client_broker, port = resolve_mqtt_broker_endpoints(
            agent_broker,
            client_broker,
            port,
            tls_connection=tls_connection,
        )
        if requested_broker and requested_broker.lower() != client_broker.lower():
            print(f"WARAPS broker {requested_broker} resolved to {client_broker} for this container")
        self.subsystem_integration_session.cancel()
        session = LiveSubsystemIntegrationSession(
            mqtt_connection=MQttConnectionInfo(
                user=user, password=password, agent_broker=agent_broker, client_broker=client_broker, port=port, tls_connection=tls_connection, allow_certificates=allow_certificates
            ),
            reference_geofence=reference_geofence,
            send_payload=self.send_payload,
        )
        try:
            await session.start()
        except Exception:
            # Leave the slot empty so the next attempt starts clean instead of
            # inheriting half-connected MQTT clients from the failed one.
            session.cancel()
            self.subsystem_integration_session = EmptySubsystemIntegrationSession(send_payload=self.send_payload)
            self.scenario_session.set_monitor_session(self.subsystem_integration_session.monitor_session)
            raise
        self.subsystem_integration_session = session

    def disconnect_from_waraps(self) -> None:
        self.send_payload(make_waraps_status_message(status="disconnected"))
        self.subsystem_integration_session.cancel()
        self.subsystem_integration_session = EmptySubsystemIntegrationSession(send_payload=self.send_payload)
        self.scenario_session.set_monitor_session(self.subsystem_integration_session.monitor_session)

    def set_monitor_session(self, name: str, topic: str, scope: str, colregs_constraints_content: str) -> None:
        self.subsystem_integration_session.set_monitor_session(name=name, topic=topic, scope=scope, colregs_constraints_content=colregs_constraints_content)
        self.scenario_session.set_monitor_session(self.subsystem_integration_session.monitor_session)

    def shut_down_monitor(self) -> None:
        self.send_payload(make_monitor_status_message(status="disconnected"))
        self.subsystem_integration_session.reset_monitor_session()
        self.scenario_session.set_monitor_session(self.subsystem_integration_session.monitor_session)

    def set_scenario_session(self, scenario_id: str, file_name: str, file_path: str, file_content: str) -> None:
        self.subsystem_integration_session.reset_simulation_session()
        self.scenario_session = LiveScenarioSession(
            scenario_id=scenario_id, file_name=file_name, file_path=file_path, file_content=file_content, monitor_session=self.subsystem_integration_session.monitor_session, send_payload=self.send_payload
        )

    async def monitor_scene(self, request_id: str, scenario_content: str) -> None:
        """Run a scene loaded on the frontend through the active monitor (live or empty).

        The monitored frame comes back as a `generated_scene` message carrying `request_id`.
        """
        raw_data = json.loads(scenario_content)
        if isinstance(raw_data, dict) and raw_data.get("trajectories") is not None:
            scene = TrajectoryData.from_payload(raw_data).trajectories.initial_scene
            valid = True
        else:
            eval_data = EvaluationData.from_dict(raw_data)
            scene = eval_data.best_scene
            valid = bool(eval_data.is_valid)
        monitor_session = self.subsystem_integration_session.monitor_session
        # The live monitor can block while it waits for the monitor heartbeat.
        await asyncio.to_thread(monitor_session.monitor_generated_scene, request_id, scene, {}, valid)

    def set_simulation_session(self, simulation_config: SimulationConfig) -> None:
        if self.scenario_session.is_initialized:
            self.subsystem_integration_session.set_simulation_session(scenario_session=self.scenario_session, simulation_config=simulation_config)
            return
        self.send_runtime_error("No scenario loaded")

    def generate_simulation_models(self, simulation_config: SimulationConfig) -> None:
        if not self.scenario_session.is_initialized:
            self.send_runtime_error("No scenario loaded")
            return
        scene = self.scenario_session.trajectories.initial_scene
        if scene is None:
            self.send_runtime_error("No initial scene found")
            return
        self.subsystem_integration_session.simulation_session.generate_vessel_models(scene, simulation_config)

    def cancel(self) -> None:
        self.subsystem_integration_session.cancel()
        self.outbound_task.cancel()
        self.waraps_connection_task.cancel()
