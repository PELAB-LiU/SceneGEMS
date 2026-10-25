import subprocess

from scenegems_tool.cluster.node.daemon.control.status_frames import UNKNOWN_REVISION, StatusFrames, software_revision
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.node_description import CapabilityOffer, NodeResources

RESOURCES = NodeResources(cpus=8.0, memory_mb=16000, free_memory_mb=9000, free_disk_mb=50000, load_average=0.25)


class Leases:
    def running_lease_ids(self):
        return ["lease-2", "lease-7"]

    def slots_in_use(self):
        return {JobType.SIMULATION_KINEMATIC: 2}


def frames(fingerprints=lambda: {"image:latest": "abc"}) -> StatusFrames:
    return StatusFrames(
        node_id="worker-1-abc123",
        node_name="worker-1",
        software_revision="0123abc",
        capabilities={JobType.SIMULATION_KINEMATIC: 4, JobType.MONITORING_POST_HOC: 1},
        labels={"site": "lab"},
        resources=lambda: RESOURCES,
        fingerprints=fingerprints,
        leases=Leases(),
    )


def test_hello_names_the_node_its_slots_images_and_running_leases():
    hello = frames().hello()
    assert (hello.node_id, hello.node_name, hello.software_revision) == ("worker-1-abc123", "worker-1", "0123abc")
    assert hello.capabilities == [CapabilityOffer(job_type=JobType.MONITORING_POST_HOC, slots=1), CapabilityOffer(job_type=JobType.SIMULATION_KINEMATIC, slots=4)]
    assert hello.labels == {"site": "lab"} and hello.resources == RESOURCES
    assert hello.fingerprints == {"image:latest": "abc"}
    assert hello.running_lease_ids == ["lease-2", "lease-7"]


def test_hello_without_docker_reports_no_fingerprints():
    def unreachable():
        raise ConnectionError("no Docker socket")

    assert frames(unreachable).hello().fingerprints == {}


def test_heartbeat_reports_slots_in_use_and_running_leases():
    heartbeat = frames().heartbeat()
    assert heartbeat.resources == RESOURCES
    assert heartbeat.slots_in_use == {JobType.SIMULATION_KINEMATIC: 2}
    assert heartbeat.running_lease_ids == ["lease-2", "lease-7"]


def test_the_configured_revision_wins():
    assert software_revision("v1.2", None) == "v1.2"
    assert software_revision(None, None) == UNKNOWN_REVISION


def test_the_revision_is_read_from_a_repository(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "start"], check=True)
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert software_revision(None, tmp_path) == head
    assert software_revision(None, tmp_path / "missing") == UNKNOWN_REVISION
