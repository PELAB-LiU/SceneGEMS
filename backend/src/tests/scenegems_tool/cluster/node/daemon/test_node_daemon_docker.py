"""The node container end to end: it pairs with a scripted master over TLS with a pinned CA and runs real jobs.

Everything the node talks to is real except the master's control logic: the security folder
and pairing (cluster/security), a NanoMQ cluster broker with TLS, the auth hook and per-node
access rules, the node image started through deploy/node/docker-compose.yml, and the
subsystem containers it starts (kinematic runners, the scene generation pool). The test
plays the master on the control WebSocket.

Images: scenegems-node:<SCENEGEMS_TEST_NODE_IMAGE_TAG>, the subsystem images with
SCENEGEMS_TEST_IMAGE_TAG (both default latest), and SCENEGEMS_BROKER_IMAGE. Containers reach
the test process and the broker through host.docker.internal, which Docker Desktop resolves.
"""

import json
import os
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest
import uvicorn

from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import certificate_sha256
from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.subsystem import IMAGE_ENVIRONMENT_VARIABLES, Subsystem, subsystem_image
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobType
from scenegems_tool.cluster.protocol.messages import Heartbeat, Hello, JobResult, JobStatus, LeaseAccept, LeaseReject, LeaseRelease, LeaseRenew, LogLines
from scenegems_tool.cluster.security.broker.auth_hook import AUTH_HOOK_PATH, create_broker_auth_app
from scenegems_tool.cluster.security.broker.broker_config import BROKER_CONFIG_MOUNT, CONFIG_FILE_NAME, TLS_PORT, ClusterBrokerSettings
from scenegems_tool.cluster.security.credentials.pairing_tokens import create_pairing_token
from scenegems_tool.cluster.security.master_security import initialize_master_security
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_replay
from tests.scenegems_tool.cluster.node.daemon.conftest import make_job, make_offer
from tests.scenegems_tool.cluster.node.daemon.fake_master import FakeMaster
from tests.scenegems_tool.cluster.node.jobs.test_jobs_in_containers import _scene_generation_payload
from tests.scenegems_tool.cluster.security.conftest import HOOK_SECRET, MASTER_PASSWORD, MASTER_USERNAME
from utils.file_system_utils import REPO_ROOT

pytestmark = [pytest.mark.docker, pytest.mark.slow]

IMAGE_TAG = os.environ.get("SCENEGEMS_TEST_IMAGE_TAG", "latest")
NODE_IMAGE_TAG = os.environ.get("SCENEGEMS_TEST_NODE_IMAGE_TAG", "latest")
BROKER_IMAGE = os.environ.get("SCENEGEMS_BROKER_IMAGE", "scenegems-mqtt-broker:latest")
COMPOSE_FILE = Path(REPO_ROOT) / "deploy" / "node" / "docker-compose.yml"
HOST = "host.docker.internal"
JOB_TIMEOUT_S = 300.0
BACKGROUND = (Heartbeat, JobStatus, LogLines, LeaseRenew)


def _docker(*arguments: str, check: bool = True, timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *arguments], capture_output=True, text=True, check=check, timeout=timeout)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _image(subsystem: Subsystem) -> str:
    return subsystem_image(subsystem).rsplit(":", 1)[0] + f":{IMAGE_TAG}"


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    """Master security, auth hook, cluster broker and the fake master: what a node sees of its master."""
    if _docker("info", check=False).returncode != 0:
        pytest.skip("Docker engine is not reachable")
    for image in (f"scenegems-node:{NODE_IMAGE_TAG}", BROKER_IMAGE, _image(Subsystem.SCENARIO_EXECUTION), _image(Subsystem.SCENE_GENERATION)):
        if _docker("image", "inspect", image, check=False).returncode != 0:
            pytest.fail(f"Image {image} is missing; build it with ./build.sh --node --backend or set the test image tags")

    hook_port, broker_port = _free_port(), _free_port()
    security = initialize_master_security(
        tmp_path_factory.mktemp("security"),
        master_id=f"m{uuid.uuid4().hex[:6]}",
        addresses=["127.0.0.1", HOST],
        master_broker_username=MASTER_USERNAME,
        master_broker_password=MASTER_PASSWORD,
        broker=ClusterBrokerSettings(auth_hook_url=f"http://{HOST}:{hook_port}{AUTH_HOOK_PATH}", auth_hook_secret=HOOK_SECRET),
        broker_public_host=HOST,
        broker_public_port=broker_port,
    )
    hook = uvicorn.Server(uvicorn.Config(create_broker_auth_app(security.store, HOOK_SECRET), host="0.0.0.0", port=hook_port, log_level="warning"))
    hook_thread = threading.Thread(target=hook.run, daemon=True)
    hook_thread.start()
    broker = f"scenegems-test-cluster-broker-{uuid.uuid4().hex[:8]}"
    _docker(
        "run", "-d", "--name", broker, "--add-host", f"{HOST}:host-gateway", "-p", f"{broker_port}:{TLS_PORT}",
        "-v", f"{security.layout.broker_folder.resolve().as_posix()}:{BROKER_CONFIG_MOUNT}:ro",
        BROKER_IMAGE, "nanomq", "start", "--conf", f"{BROKER_CONFIG_MOUNT}/{CONFIG_FILE_NAME}",
    )  # fmt: skip
    master = FakeMaster(security, host=HOST, heartbeat_interval_s=1.0, lease_timeout_s=30.0).start(bind="0.0.0.0")
    try:
        yield master
    finally:
        master.stop()
        _docker("rm", "-f", broker, check=False)
        hook.should_exit = True
        hook_thread.join(timeout=10)


class NodeContainer:
    """deploy/node/docker-compose.yml with a test env file: up, logs, exec and down with volumes."""

    def __init__(self, env_file: Path, name: str):
        self.env_file = env_file
        self.name = name

    def compose(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "--env-file", str(self.env_file), *arguments], capture_output=True, text=True, check=check, timeout=300)

    def logs(self) -> str:
        return _docker("logs", self.name, check=False).stdout[-6000:]


@pytest.fixture(scope="module")
def node(cluster, tmp_path_factory):
    node_name = f"docker-{uuid.uuid4().hex[:6]}"
    env_file = tmp_path_factory.mktemp("node") / "node.env"
    values = {
        "SCENEGEMS_MASTER_URL": cluster.url,
        "SCENEGEMS_MASTER_ID": cluster.security.master_id,
        "SCENEGEMS_MASTER_CA_SHA256": certificate_sha256(cluster.security.ca_certificate_pem),
        "SCENEGEMS_PAIRING_TOKEN": create_pairing_token(cluster.security.store).token,
        "SCENEGEMS_NODE_NAME": node_name,
        "SCENEGEMS_NODE_CAPABILITIES": "simulation.kinematic:2,scene_generation:1",
        "SCENEGEMS_NODE_LABELS": "test=docker",
        "SCENEGEMS_NODE_IMAGE_TAG": NODE_IMAGE_TAG,
        "SCENEGEMS_SOFTWARE_REVISION": "docker-test",
        **{variable: _image(subsystem) for subsystem, variable in IMAGE_ENVIRONMENT_VARIABLES.items()},
    }
    env_file.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    container = NodeContainer(env_file, f"scenegems-node-{cluster.security.master_id}-{node_name}")
    container.compose("up", "-d")
    try:
        yield container
    finally:
        container.compose("down", "--volumes", "--timeout", "60", check=False)


def _running_runners(master_id: str, node_id: str) -> int:
    prefix = InstanceScope.per_job(master_id, node_id, "x").docker_name.rsplit("job-", 1)[0] + "job-"
    names = _docker("ps", "--format", "{{.Names}}", check=False).stdout.split()
    return sum(1 for name in names if name.startswith(prefix) and name.endswith("-runner"))


class RunnerWatch:
    """Samples how many kinematic runner containers of the node run at once."""

    def __init__(self, master_id: str, node_id: str):
        self.most = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, args=(master_id, node_id), daemon=True)

    def _watch(self, master_id: str, node_id: str) -> None:
        while not self._stop.is_set():
            self.most = max(self.most, _running_runners(master_id, node_id))
            time.sleep(0.5)

    def __enter__(self) -> "RunnerWatch":
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def _answers(connection, count: int) -> dict:
    answers = {}
    while len(answers) < count:
        frame = connection.expect((LeaseAccept, LeaseReject), skip=BACKGROUND)
        answers[frame.lease_id] = frame
    return answers


def _results(connection, count: int, payload: dict) -> dict:
    """Results until count arrived; the rejected kinematic job is offered again once a kinematic slot is free."""
    results = {}
    offered_again = False
    while len(results) < count:
        frame = connection.expect((JobResult, LeaseAccept), timeout_s=JOB_TIMEOUT_S, skip=BACKGROUND)
        if isinstance(frame, JobResult):
            results[frame.lease_id] = frame
        if not offered_again and any(lease.startswith("kinematic") for lease in results):
            connection.send(make_offer("kinematic-2", make_job("kinematic-2", payload=payload)))
            offered_again = True
    return results


def test_the_node_container_pairs_and_runs_jobs_within_its_slots(cluster, node, head_on_trajectories):
    try:
        connection = cluster.wait_for_connection(timeout_s=120)
    except AssertionError:
        pytest.fail(f"The node never connected:\n{node.logs()}")
    hello = connection.expect(Hello)
    master_id, node_id = cluster.security.master_id, hello.node_id
    assert hello.node_name == node.name.rsplit(f"{master_id}-", 1)[1] and hello.labels == {"test": "docker"}
    assert hello.software_revision == "docker-test" and hello.resources.cpus >= 1 and hello.resources.memory_mb > 0
    assert {offer.job_type: offer.slots for offer in hello.capabilities} == {JobType.SIMULATION_KINEMATIC: 2, JobType.SCENE_GENERATION: 1}

    # The pairing state is owner-only inside the node's volume, and the token is used up.
    assert _docker("exec", node.name, "stat", "-c", "%a", "/var/lib/scenegems-node/pairing.json").stdout.strip() == "600"
    assert len(cluster.pairing_requests) == 1

    payload = {"trajectories": head_on_trajectories.to_dict(), "include_trajectories": False}
    with RunnerWatch(master_id, node_id) as runners:
        try:
            for index in range(3):
                connection.send(make_offer(f"kinematic-{index}", make_job(f"kinematic-{index}", payload=payload)))
            connection.send(make_offer("scene-0", make_job("scene-0", job_type=JobType.SCENE_GENERATION, payload=_scene_generation_payload())))
            answers = _answers(connection, 4)
            assert {lease for lease, frame in answers.items() if isinstance(frame, LeaseAccept)} == {"kinematic-0", "kinematic-1", "scene-0"}
            assert "2 simulation.kinematic slots are in use" in answers["kinematic-2"].reason
            results = _results(connection, 4, payload)
        except AssertionError as error:
            pytest.fail(f"{error}\nNode log:\n{node.logs()}")

    expected_digest = run_kinematic_replay(head_on_trajectories).state_digest()
    for lease in ("kinematic-0", "kinematic-1", "kinematic-2"):
        assert results[lease].outcome == JobOutcome.SUCCEEDED, results[lease].error
        assert results[lease].result["state_digest"] == expected_digest
        assert results[lease].idempotency_key == f"{lease}/key"
    scene = results["scene-0"]
    assert scene.outcome == JobOutcome.SUCCEEDED, scene.error
    assert scene.result["request_id"] == "scene-0-1" and isinstance(scene.result["valid"], bool)
    assert 1 <= runners.most <= 2
    assert max(sum(heartbeat.slots_in_use.values()) for heartbeat in connection.received(Heartbeat)) <= 3

    # The scene generation pool reached the broker over TLS with the CA from the trust volume.
    pool = InstanceScope.pooled(master_id, node_id, Subsystem.SCENE_GENERATION.value).docker_name
    mounts = _docker("inspect", "--format", "{{range .Mounts}}{{.Name}}:{{.Destination}} {{end}}", pool).stdout
    assert f"{node.name}-trust:/etc/scenegems/trust" in mounts

    # Stopping the node removes its pool and leaves nothing of its instances behind.
    node.compose("stop", "--timeout", "60")
    remaining = [name for name in _docker("ps", "-a", "--format", "{{.Names}}").stdout.split() if name.startswith(f"scenegems-{master_id}-{node_id}-")]
    assert remaining == []
    assert not connection.received(LeaseRelease)  # nothing was running at the stop


# Every job type's node side in the node image: its payload check and what run() does before
# it starts a container. The image carries only the daemon's requirements, so a missing
# library shows up here and not in the middle of a campaign.
NODE_SIDE_CHECK = """
import json
import math
import sys
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.cluster.node.jobs import job_types, simulation_ardupilot_job
from scenegems_tool.cluster.node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence
def vessel(vessel_id, own):
    return ConcreteActor.from_dict({"id": vessel_id, "type": "OSPassengerShip" if own else "PassengerShip", "length": 30.0, "breadth": 10.0, "safety_radius": 120.0,
        "is_vessel": True, "_is_os": own, "_max_speed": 20.57778, "_max_angular_speed": 0.05, "_max_acceleration": 0.4})

scene = ConcreteScene({vessel(0, True): ActorState(0.0, 0.0, 8.0, 0.0), vessel(1, False): ActorState(3000.0, 0.0, 8.0, math.pi)})
trajectories = TrajectoryBuilder.default_trajectory_from_scene(scene, 1, 60).to_dict()
geofence = {"latitude": 57.7, "longitude": 11.9, "radius_meters": 2000.0}
payloads = {
    JobType.SCENE_GENERATION: json.load(sys.stdin),  # the test data folders are not in the image
    JobType.TRAJECTORY_GENERATION: {"scenario_content": "{}", "colregs_constraints_content": "", "params": {"maxIterations": 100}},
    JobType.SIMULATION_KINEMATIC: {"mode": "usv_navigation", "trajectories": trajectories},
    JobType.SIMULATION_ARDUPILOT: {"simulation_layer": "ardupilot_sim", "trajectories": trajectories, "geofence": geofence},
    JobType.MONITORING_POST_HOC: {"trajectories": trajectories},
}
models = {
    JobType.SCENE_GENERATION: "SceneGenerationPayload",
    JobType.TRAJECTORY_GENERATION: "TrajectoryGenerationPayload",
    JobType.SIMULATION_KINEMATIC: "KinematicSimulationPayload",
    JobType.SIMULATION_ARDUPILOT: "ArduPilotSimulationPayload",
    JobType.MONITORING_POST_HOC: "PostHocMonitoringPayload",
}
for job_type, payload in payloads.items():
    model = getattr(job_types.job_type_module(job_type), models[job_type])
    parse_payload(model, JobSpec(job_id="check", job_type=job_type, payload=payload, attempt=1, idempotency_key="check"))
node = NodeContext("m1", "n1", MQttConnectionInfo("u", "p", "broker", "broker", 8883, True, False), Geofence(57.7, 11.9, 2000.0), slots={JobType.SIMULATION_ARDUPILOT: 1})
job = JobSpec(job_id="check", job_type=JobType.SIMULATION_ARDUPILOT, payload=payloads[JobType.SIMULATION_ARDUPILOT], attempt=1, idempotency_key="check")
stack = simulation_ardupilot_job.build_job_stack(job, node, parse_payload(simulation_ardupilot_job.ArduPilotSimulationPayload, job))
assert "runner" in stack.compose["services"] and len(stack.compose["services"]) >= 3, stack.compose["services"].keys()
print("node side ok:", ", ".join(sorted(job_type.value for job_type in payloads)))
"""


def test_every_job_type_s_node_side_runs_in_the_node_image():
    if _docker("info", check=False).returncode != 0:
        pytest.skip("Docker engine is not reachable")
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", f"scenegems-node:{NODE_IMAGE_TAG}", "python", "-c", NODE_SIDE_CHECK],
        input=json.dumps(_scene_generation_payload()),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert "node side ok: monitoring.post_hoc, scene_generation, simulation.ardupilot, simulation.kinematic, trajectory_generation" in result.stdout
