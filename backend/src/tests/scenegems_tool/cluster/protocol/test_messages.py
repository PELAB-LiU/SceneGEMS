import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import Hello, JobStatus, LeaseAccept, Welcome
from scenegems_tool.cluster.protocol.node_description import CapabilityOffer
from scenegems_tool.cluster.protocol.version import PROTOCOL_VERSION


def test_frames_carry_the_protocol_version():
    assert LeaseAccept(lease_id="l1").protocol_version == PROTOCOL_VERSION


def test_frame_of_another_version_does_not_validate():
    with pytest.raises(ValidationError, match="Incompatible cluster protocol version"):
        LeaseAccept(lease_id="l1", protocol_version=PROTOCOL_VERSION + 1)


def test_frames_are_immutable():
    frame = LeaseAccept(lease_id="l1")
    with pytest.raises(ValidationError):
        frame.lease_id = "l2"


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        LeaseAccept(lease_id="l1", lease="l1")


def test_capability_needs_a_slot():
    with pytest.raises(ValidationError):
        CapabilityOffer(job_type=JobType.SCENE_GENERATION, slots=0)


def test_hello_lists_capabilities_with_slots(resources):
    hello = Hello(
        node_id="n1",
        node_name="lab-1",
        software_revision="4ac7ef2",
        capabilities=[CapabilityOffer(job_type=JobType.SIMULATION_KINEMATIC, slots=4)],
        resources=resources,
    )
    assert hello.capabilities[0].slots == 4
    assert hello.running_lease_ids == []


def test_hello_names_the_machine_optionally(resources):
    base = dict(node_id="n1", node_name="lab-1", software_revision="4ac7ef2", capabilities=[CapabilityOffer(job_type=JobType.SCENE_GENERATION, slots=1)], resources=resources)
    assert Hello(**base).machine is None
    hello = Hello(**base, machine="lab-pc-3")
    assert Hello.model_validate_json(hello.model_dump_json()).machine == "lab-pc-3"


def test_progress_is_a_fraction():
    with pytest.raises(ValidationError):
        JobStatus(lease_id="l1", job_id="j1", progress=1.5)


def test_welcome_needs_positive_intervals():
    with pytest.raises(ValidationError):
        Welcome(master_id="m1", heartbeat_interval_s=0.0, lease_timeout_s=30.0)
