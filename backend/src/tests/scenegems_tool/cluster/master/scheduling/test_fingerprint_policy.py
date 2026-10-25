import anyio
import pytest

from scenegems_tool.cluster.fingerprints.job_images import GAZEBO_IMAGE, MONITORING_IMAGE, SCENARIO_EXECUTION_IMAGE, SCENE_GENERATION_IMAGE, SITL_IMAGE
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints, ListingState, node_mismatches, with_required_fingerprints
from scenegems_tool.cluster.protocol.jobs import JobRequirements, JobSubmission, JobType
from tests.scenegems_tool.cluster.master.conftest import EXPECTED
from tests.scenegems_tool.cluster.master.fake_stores import InMemoryNodeStore
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello


def _load(expected: ExpectedFingerprints) -> None:
    anyio.run(expected.load)


def test_a_fixed_listing_is_ready():
    expected = ExpectedFingerprints.fixed({"a:latest": "1"})
    assert expected.state == ListingState.READY and expected.current() == {"a:latest": "1"}


def test_the_listing_is_computed_once_on_load():
    calls = []
    expected = ExpectedFingerprints(lambda: calls.append(1) or {"a:latest": "1"})
    assert expected.state == ListingState.PENDING and expected.current() is None
    _load(expected)
    _load(expected)
    assert expected.current() == {"a:latest": "1"} and calls == [1]


@pytest.mark.parametrize("compute, message", [(lambda: (_ for _ in ()).throw(RuntimeError("no bash")), "no bash"), (lambda: {}, "empty")])
def test_a_failed_listing_leases_nothing_and_says_why(compute, message):
    expected = ExpectedFingerprints(compute)
    _load(expected)
    assert expected.state == ListingState.FAILED and expected.current() is None and message in expected.error


def test_a_submission_gets_the_fingerprints_of_its_images():
    submission = with_required_fingerprints(JobSubmission(job_type=JobType.SIMULATION_ARDUPILOT, payload={"simulation_layer": "gazebo"}), EXPECTED)
    assert submission.requirements.fingerprints == {SCENARIO_EXECUTION_IMAGE: "fp-execution", SITL_IMAGE: "fp-sitl", GAZEBO_IMAGE: "fp-gazebo"}


def test_a_submission_that_names_fingerprints_keeps_them():
    pinned = JobRequirements(fingerprints={MONITORING_IMAGE: "campaign-pin"}, labels={"site": "lab"})
    submission = JobSubmission(job_type=JobType.MONITORING_POST_HOC, requirements=pinned)
    assert with_required_fingerprints(submission, EXPECTED) is submission


def test_other_requirements_are_kept():
    submission = JobSubmission(job_type=JobType.SCENE_GENERATION, requirements=JobRequirements(labels={"site": "lab"}, min_memory_mb=100))
    required = with_required_fingerprints(submission, EXPECTED).requirements
    assert required.labels == {"site": "lab"} and required.min_memory_mb == 100 and required.fingerprints == {SCENE_GENERATION_IMAGE: "fp-scene"}


def test_node_mismatches_cover_the_images_of_its_capabilities_only():
    node = InMemoryNodeStore(ManualClock()).register(make_hello("n", slots={JobType.SCENE_GENERATION: 1}, fingerprints={SCENE_GENERATION_IMAGE: "fp-scene", MONITORING_IMAGE: "old"}))
    assert node_mismatches(node, EXPECTED) == []
    stale = InMemoryNodeStore(ManualClock()).register(make_hello("n", slots={JobType.MONITORING_POST_HOC: 1}, fingerprints={MONITORING_IMAGE: "old"}))
    assert [(mismatch.image, mismatch.actual) for mismatch in node_mismatches(stale, EXPECTED)] == [(MONITORING_IMAGE, "old")]
