"""Monitor frames of a recorded run on demand, on a real Postgres (-m postgres), through a test client."""

import pytest
from starlette.testclient import TestClient

from scenegems_tool.cluster.master.api.master_apps import create_operator_app
from scenegems_tool.cluster.master.api.run_frames_routes import FRAMES_PRIORITY, frames_key
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.protocol.artifacts import ArtifactKind, ArtifactRef
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobType
from scenegems_tool.cluster.protocol.messages import JobResult
from scenegems_tool.cluster.protocol.routes import CAMPAIGNS_PATH, JOBS_PATH
from scenegems_tool.persistence.schema import TrajectoryGeneratorImplementation
from scenegems_tool.persistence.stores import AssuranceStores, JobStore, NewCase, NewRunRecord, NodeStore
from tests.scenegems_tool.cluster.master.api.test_campaign_routes import CLASS_A, YAML, small_config
from tests.scenegems_tool.cluster.master.conftest import EXPECTED, KINEMATIC
from tests.scenegems_tool.cluster.payloads import valid_payload
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello

pytestmark = pytest.mark.postgres

NODE = "lab-1"
STATE_LOG = ArtifactRef(sha256="a" * 64, size_bytes=4096, kind=ArtifactKind.TRAJECTORIES, pointer="/trajectories").model_dump(mode="json")
FRAMES = ArtifactRef(sha256="b" * 64, size_bytes=8192, kind=ArtifactKind.FRAMES).model_dump(mode="json")


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def stores(session_factory, clock) -> AssuranceStores:
    return AssuranceStores.create(session_factory, clock)


@pytest.fixture
def plane(session_factory, clock) -> ControlPlane:
    nodes = NodeStore(session_factory, clock)
    nodes.register(make_hello(NODE, slots={KINEMATIC: 1, JobType.MONITORING_POST_HOC: 1}, fingerprints=dict(EXPECTED)))
    return ControlPlane("lab-master", nodes, JobStore(session_factory, clock), ExpectedFingerprints.fixed(EXPECTED), clock=clock)


@pytest.fixture
def client(plane, stores):
    with TestClient(create_operator_app(plane, assurance=stores)) as client:
        yield client


@pytest.fixture
def campaign(client) -> dict:
    return client.post(CAMPAIGNS_PATH, content=small_config(), headers=YAML).json()


def _run_job(plane: ControlPlane, job_id: str, result: dict) -> None:
    """The node runs the job and reports its result."""
    lease = plane.jobs.claim_next(NODE, 30.0)
    assert lease is not None and lease.job.job_id == job_id
    plane.jobs.accept(lease.lease_id, 30.0)
    plane.jobs.report_result(JobResult(lease_id=lease.lease_id, job_id=job_id, idempotency_key=lease.job.idempotency_key, outcome=JobOutcome.SUCCEEDED, result=result))


def _run_record(stores, campaign_id: str, **fields) -> int:
    (case,) = stores.cases.create_cases(campaign_id, [NewCase(CLASS_A, 0, 100)])
    record = stores.results.add_run_record(NewRunRecord(case.case_id, 0, TrajectoryGeneratorImplementation.STRAIGHT, True, {"mode": "replay"}, {}, case.seed, **fields))
    return record.run_record_id


def _path(campaign_id: str, run_record_id: int) -> str:
    return f"{CAMPAIGNS_PATH}/{campaign_id}/run-records/{run_record_id}/frames"


def test_frames_are_requested_once_and_answered_with_the_job_then_the_frames(client, plane, stores, campaign):
    simulation = client.post(JOBS_PATH, json={"job_type": KINEMATIC.value, "payload": valid_payload(KINEMATIC)}).json()
    _run_job(plane, simulation["job_id"], {"trajectories": STATE_LOG, "steps": 10})
    run_record_id = _run_record(stores, campaign["campaign_id"], artifacts={"state_log": STATE_LOG["sha256"]}, job_id=simulation["job_id"])
    path = _path(campaign["campaign_id"], run_record_id)
    assert client.get(path).status_code == 404  # nothing requested yet

    first = client.post(path)
    assert first.status_code == 201
    view = first.json()
    job = view["job"]
    assert view["run_record_id"] == run_record_id and view["frames"] is None
    assert job["job_type"] == "monitoring.post_hoc" and job["state"] == "queued" and job["priority"] == FRAMES_PRIORITY
    assert job["idempotency_key"] == frames_key(run_record_id)
    assert set(job["requirements"]["fingerprints"].values()) <= set(EXPECTED.values()) and job["requirements"]["fingerprints"]
    assert job["allowed_nodes"] == []  # the campaign may use every node
    payload = plane.jobs.get(job["job_id"]).payload
    assert payload["trajectories"] == STATE_LOG  # the simulation's own reference, pointer included
    assert payload["include_frames"] is True and payload["scenario_id"] == f"run-record-{run_record_id}"
    assert payload["colregs_constraints_content"] == stores.campaigns.config_version(campaign["campaign_id"]).config["domain"]["colregs_constants"]

    again = client.post(path)
    assert again.status_code == 200 and again.json()["job"]["job_id"] == job["job_id"]
    assert client.get(path).json()["job"]["job_id"] == job["job_id"]

    _run_job(plane, job["job_id"], {"frames": FRAMES, "passed": True})
    done = client.get(path).json()
    assert done["job"]["state"] == "succeeded" and done["frames"] == FRAMES


def test_the_frames_job_keeps_to_the_campaigns_selected_nodes(client, plane, stores):
    campaign = client.post(CAMPAIGNS_PATH, content=small_config(resources={"priority": 0, "nodes": [NODE, "lab-2"]}), headers=YAML).json()
    stores.artifacts.insert_if_absent(STATE_LOG["sha256"], "trajectories", 4096, "application/json")
    run_record_id = _run_record(stores, campaign["campaign_id"], artifacts={"state_log": STATE_LOG["sha256"]})
    job = client.post(_path(campaign["campaign_id"], run_record_id)).json()["job"]
    assert job["allowed_nodes"] == [NODE, "lab-2"]


def test_without_the_simulation_job_the_reference_comes_from_the_artifact_record(client, plane, stores, campaign):
    stores.artifacts.insert_if_absent(STATE_LOG["sha256"], "trajectories", 4096, "application/json")
    run_record_id = _run_record(stores, campaign["campaign_id"], artifacts={"state_log": STATE_LOG["sha256"]})
    response = client.post(_path(campaign["campaign_id"], run_record_id))
    assert response.status_code == 201
    payload = plane.jobs.get(response.json()["job"]["job_id"]).payload
    assert payload["trajectories"] == {"sha256": STATE_LOG["sha256"], "size_bytes": 4096, "kind": "trajectories", "media_type": "application/json", "pointer": None}


def test_a_run_without_a_kept_state_log_is_refused(client, stores, campaign):
    without = _run_record(stores, campaign["campaign_id"])
    response = client.post(_path(campaign["campaign_id"], without))
    assert response.status_code == 409 and "has no state log" in response.json()["detail"]
    (case,) = stores.cases.create_cases(campaign["campaign_id"], [NewCase(CLASS_A, 1, 101)])
    gone = stores.results.add_run_record(NewRunRecord(case.case_id, 0, TrajectoryGeneratorImplementation.STRAIGHT, True, {}, {}, 1, artifacts={"state_log": "c" * 64})).run_record_id
    response = client.post(_path(campaign["campaign_id"], gone))
    assert response.status_code == 409 and "no longer stored" in response.json()["detail"]


def test_unknown_campaigns_and_run_records_are_404(client, stores, campaign):
    run_record_id = _run_record(stores, campaign["campaign_id"], artifacts={"state_log": "a" * 64})
    other = client.post(CAMPAIGNS_PATH, content=small_config(), headers=YAML).json()
    assert client.post(_path("no-such-campaign", run_record_id)).status_code == 404
    assert client.post(_path(campaign["campaign_id"], run_record_id + 1000)).status_code == 404
    assert client.post(_path(other["campaign_id"], run_record_id)).status_code == 404
    assert client.get(_path(other["campaign_id"], run_record_id)).status_code == 404
