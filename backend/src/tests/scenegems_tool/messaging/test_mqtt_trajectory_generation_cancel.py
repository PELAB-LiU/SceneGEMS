"""Cancelling a search of a trajectory generation pool: only the named request's search stops.

The service is the real one; its workers run as threads instead of processes, and each stands-in
search blocks until the test wakes it, then reports whether its own cancel event was set. The
test steps the pool (`_start_worker`) and the publisher (`_publish_next_output`) itself.
"""

import queue
import threading

import pytest

from scenegems_tool.messaging import mqtt_trajectory_generation_service as service_module
from scenegems_tool.messaging.mqtt_trajectory_generation_client import MqttTrajectoryGenerationClient
from scenegems_tool.messaging.mqtt_trajectory_generation_service import MqttTrajectoryGenerationService
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TRAJECTORY_GENERATION_SERVICE_NAME, TRAJECTORY_GENERATION_SERVICE_TOPIC
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline

_JOIN_S = 10.0  # a safety net only: every wait below ends when the test sets the event


class _ThreadProcess:
    def __init__(self, searches, target, args, name, daemon):
        self._searches = searches
        self._request_id = args[0].request_id
        self._thread = threading.Thread(target=target, args=args, name=name, daemon=daemon)

    def start(self):
        self._thread.start()

    def is_alive(self):
        return self._thread.is_alive()

    def join(self, timeout=None):
        self._thread.join(timeout)

    def terminate(self):
        self._searches.wake_event(self._request_id).set()  # the process ends at once

    kill = terminate


class _Searches:
    """The worker: a search waits for its wake event, then ends cancelled or with its plan."""

    def __init__(self):
        self.started = []
        self.wake = {}
        self.threads = {}

    def __call__(self, task, preview_queue, result_queue, cancel_event):
        self.started.append(task.request_id)
        self.threads[task.request_id] = threading.current_thread()
        assert self.wake_event(task.request_id).wait(_JOIN_S)
        if cancel_event.is_set():
            result_queue.put((task, None, False, False, "cancelled"))
        else:
            result_queue.put((task, {"plan": task.request_id}, True, True, None))

    def wake_event(self, request_id):
        return self.wake.setdefault(request_id, threading.Event())

    def finish(self, request_id):
        self.wake_event(request_id).set()
        self.threads[request_id].join(_JOIN_S)
        assert not self.threads[request_id].is_alive()


@pytest.fixture
def searches(monkeypatch):
    searches = _Searches()
    monkeypatch.setattr(service_module, "Process", lambda **arguments: _ThreadProcess(searches, **arguments))
    monkeypatch.setattr(service_module, "run_trajectory_generation_worker", searches)
    return searches


def _service(max_workers):
    service = offline(MqttTrajectoryGenerationService(CONNECTION, GEOFENCE, max_workers=max_workers))
    service.task_queue, service.preview_queue, service.result_queue = queue.Queue(), queue.Queue(), queue.Queue()
    return service


def _start(service, request_id):
    command = {
        "execution-unit": TRAJECTORY_GENERATION_SERVICE_NAME,
        "command": "start-task",
        "task-uuid": f"uuid-{request_id}",
        "task": {"name": "generate-trajectories", "params": {"request-id": request_id, "scenario-content": "{}", "colregs-constraints-content": "", "params": {}}},
    }
    deliver(service, service.exec_command_topic, command)


def _cancel(service, request_id):
    """The cancel exactly as a job's client sends it."""
    client = offline(MqttTrajectoryGenerationClient(CONNECTION, TRAJECTORY_GENERATION_SERVICE_TOPIC, GEOFENCE, TRAJECTORY_GENERATION_SERVICE_NAME, send_payload=lambda message: None))
    client.publish_cancel_command(request_id)
    [(_, command)] = client.client.published
    deliver(service, service.exec_command_topic, command)


def _start_queued(service):
    while not service.task_queue.empty():
        service._start_worker(service.task_queue.get_nowait())


def _results(service):
    while service._publish_next_output(preview_timeout=0):
        pass
    return {message["request-id"]: message for topic, message in service.client.published if topic == service.planned_trajectory_topic}


def _cancelled(service, request_id):
    return service._cancel_events[f"uuid-{request_id}"].is_set()


def test_cancelling_one_of_two_running_searches_leaves_the_other_to_its_result(searches):
    service = _service(max_workers=2)
    _start(service, "campaign")
    _start(service, "workbench")
    _start_queued(service)
    assert searches.started == ["campaign", "workbench"]

    _cancel(service, "workbench")
    assert _cancelled(service, "workbench") and not _cancelled(service, "campaign")
    searches.finish("workbench")
    searches.finish("campaign")

    results = _results(service)
    assert (results["workbench"]["valid"], results["workbench"]["error-message"]) == (False, "cancelled")
    assert (results["campaign"]["valid"], results["campaign"]["complete"], results["campaign"]["trajectory-data"]) == (True, True, {"plan": "campaign"})
    assert service.current_tasks == [] and service._cancel_events == {}


def test_a_search_cancelled_while_it_queues_never_starts(searches):
    service = _service(max_workers=2)
    for request_id in ("a", "b", "c"):
        _start(service, request_id)
    _cancel(service, "c")
    _start_queued(service)
    assert searches.started == ["a", "b"]
    assert [task.request_id for task in service.current_tasks] == ["a", "b"] and not _cancelled(service, "a") and not _cancelled(service, "b")
    searches.finish("a")
    searches.finish("b")
    assert sorted(_results(service)) == ["a", "b"]  # nothing for the search that never ran


@pytest.mark.parametrize("request_id", [None, "unknown"])
def test_a_cancel_for_no_request_or_an_unknown_one_stops_nothing(searches, request_id):
    service = _service(max_workers=2)
    _start(service, "a")
    _start_queued(service)
    if request_id is None:
        deliver(service, service.exec_command_topic, {"execution-unit": TRAJECTORY_GENERATION_SERVICE_NAME, "command": "signal-task", "signal": {"name": "cancel"}})
    else:
        _cancel(service, request_id)
    assert not _cancelled(service, "a")
    searches.finish("a")
    assert _results(service)["a"]["valid"] is True


def test_a_one_worker_pool_supersedes_the_search_it_holds(searches):
    service = _service(max_workers=1)
    _start(service, "old")
    _start_queued(service)
    old_event = service._cancel_events["uuid-old"]
    _start(service, "new")
    assert old_event.is_set() and not _cancelled(service, "new")
    assert [task.request_id for task in service.current_tasks] == ["new"]
    searches.finish("old")
    _start_queued(service)
    searches.finish("new")
    results = _results(service)
    assert results["old"]["error-message"] == "cancelled" and results["new"]["valid"] is True


def test_stopping_the_service_cancels_every_search(searches):
    service = _service(max_workers=2)
    _start(service, "a")
    _start(service, "b")
    _start_queued(service)
    events = list(service._cancel_events.values())
    service.stop_runtime()
    assert all(event.is_set() for event in events)
    assert service.current_tasks == [] and service._cancel_events == {}
    assert not any(thread.is_alive() for thread in searches.threads.values())
