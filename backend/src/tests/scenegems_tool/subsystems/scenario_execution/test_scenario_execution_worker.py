"""ScenarioExecutionWorker: which driver runs an instance, and the states a lockstep run publishes."""

import queue

import pytest

from scenegems_tool.gateway.protocol import SimulationStatus
from scenegems_tool.subsystems.scenario_execution import scenario_execution_worker
from scenegems_tool.subsystems.scenario_execution.scenario_execution_worker import ScenarioExecutionWorker
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection, stack_instance


class FakeService:
    def __init__(self, mqtt_connection, reference_geofence):
        self.info_update_rate = 1.0
        self.task_queue = queue.Queue()
        self.states = []

    def publish_simulation_state(self, status, clock, scene):
        self.states.append((status, clock, scene))


class FakeParser:
    def __init__(self, *args, **kwargs):
        self.created = True


@pytest.fixture(autouse=True)
def fake_messaging(monkeypatch):
    monkeypatch.setattr(scenario_execution_worker, "MqttScenarioExecutionService", FakeService)
    monkeypatch.setattr(scenario_execution_worker, "SimulationParser", FakeParser)


def worker(instance, timespan=10):
    return ScenarioExecutionWorker(mqtt_connection(), GEOFENCE, instance, encounter_trajectories("head_on", timespan), 1)


def test_simulated_vessels_run_through_the_lockstep_driver():
    subject = worker(stack_instance(SimulationLayerId.KINEMATIC, [0, 1], control_layer=ControlLayerId.NONE))
    assert subject.lockstep_driver is not None and subject.simulation_parser is None


def test_an_instance_with_a_real_vessel_runs_through_arduagent():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
    instance.vessels["1"].context = AgentContext.REAL
    subject = worker(instance)
    assert subject.lockstep_driver is None and isinstance(subject.simulation_parser, FakeParser)


def test_a_lockstep_instance_is_ready_at_once_and_publishes_every_step_while_running():
    subject = worker(stack_instance(SimulationLayerId.KINEMATIC, [0, 1], control_layer=ControlLayerId.NONE, speedup=1000))
    assert subject._compute_status() == SimulationStatus.READY_TO_START
    subject._handle_start_simulation(task=None)
    subject._runtime_thread.join(30.0)
    states = subject.mqtt_service.states
    running = [(clock, scene) for status, clock, scene in states if status == SimulationStatus.RUNNING]
    assert [clock for clock, _ in running] == [float(t) for t in range(11)]
    assert all(scene is not None for _, scene in running)
    assert states[0][0] == SimulationStatus.STARTING
    assert states[-1][0] == SimulationStatus.READY_TO_START, "back to ready when the run ends"
