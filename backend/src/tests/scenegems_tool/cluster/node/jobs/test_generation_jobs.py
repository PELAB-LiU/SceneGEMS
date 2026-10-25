"""scene_generation and trajectory_generation jobs against a scripted pool: what the job sends and which reply it takes."""

import threading
from types import SimpleNamespace

import pytest

from scenegems_tool.cluster.node.jobs import scene_generation_job, trajectory_generation_job
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.messaging import mqtt_scenario_generation_client, mqtt_trajectory_generation_client
from tests.scenegems_tool.cluster.payloads import valid_payload


class _Report:
    def __init__(self):
        self.messages = []

    def status(self, message, progress=None):
        self.messages.append(message)


class _ScriptedClient:
    """Stands in for a generation client; `answer(client, command)` plays the pool's replies."""

    answer = None
    commands = []

    def __init__(self, **arguments):
        self.arguments = arguments
        self.is_connected = self.is_heartbeat_valid = True

    def connect(self):
        pass

    def disconnect(self):
        pass

    def _publish(self, *args, **options):
        type(self).commands.append((args, options))
        threading.Thread(target=type(self).answer, args=(self.arguments, args)).start()

    publish_generate_scene_command = _publish
    publish_generate_trajectories_command = _publish


@pytest.fixture
def pool(monkeypatch, node):
    def install(module, attribute, answer):
        client = type("Client", (_ScriptedClient,), {"answer": staticmethod(answer), "commands": []})
        monkeypatch.setattr(module, attribute, client)
        monkeypatch.setattr(node, "pools", SimpleNamespace(get=lambda subsystem: SimpleNamespace(mqtt_connection=node.mqtt_connection)))
        return client

    return install


def test_the_scene_job_sends_the_seed_and_takes_the_final_scene(pool, node, make_job):
    def answer(arguments, command):
        request_id = command[0]
        arguments["on_scene_result"]("someone-else", {"sample": 0}, True, True)
        arguments["on_scene_result"](request_id, {"sample": 1}, False, False)
        arguments["on_scene_result"](request_id, {"sample": 2}, False, False)
        arguments["on_scene_result"](request_id, {"sample": 3}, True, True)
        arguments["on_scene_result"](request_id, {"sample": 4}, True, True)  # never twice

    client = pool(mqtt_scenario_generation_client, "MqttScenarioGenerationClient", answer)
    report = _Report()
    result = scene_generation_job.run(make_job(JobType.SCENE_GENERATION, valid_payload(JobType.SCENE_GENERATION, seed=17)), node, report)
    assert result == {"request_id": "job-1-1", "valid": True, "evaluation_data": {"sample": 3}}
    assert client.commands[0][1] == {"seed": 17}
    assert "search sample 2" in report.messages


def test_the_trajectory_job_returns_complete(pool, node, make_job):
    def answer(arguments, command):
        arguments["send_payload"]({"type": "trajectory_generation_preview", "requestId": command[0]})
        arguments["on_result"](command[0], {"trajectories": {}}, True, False, None)

    client = pool(mqtt_trajectory_generation_client, "MqttTrajectoryGenerationClient", answer)
    report = _Report()
    payload = valid_payload(JobType.TRAJECTORY_GENERATION, seed=3, params={"generator": "straight", "timespan": 300})
    result = trajectory_generation_job.run(make_job(JobType.TRAJECTORY_GENERATION, payload), node, report)
    assert result == {"request_id": "job-1-1", "valid": True, "complete": False, "trajectory_data": {"trajectories": {}}, "error_message": None}
    (request_id, scenario_content, constants, params), options = client.commands[0]
    assert options == {"seed": 3} and params.generator.value == "straight" and params.timespan == 300.0
    assert "search preview 1" in report.messages
