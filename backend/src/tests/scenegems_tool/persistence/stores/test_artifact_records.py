import pytest

from scenegems_tool.persistence.schema import ArtifactHolderKind
from scenegems_tool.persistence.stores import ArtifactMismatch, UnknownArtifact
from tests.scenegems_tool.persistence.stores.builders import START, sha256_of

pytestmark = pytest.mark.postgres

SCENE, TRAJECTORIES = sha256_of("scene"), sha256_of("trajectories")
CASE = ArtifactHolderKind.CASE
UNUSED_S = 3600.0


def _record(stores, artifact_hash=SCENE, size=1200, kind="scene"):
    return stores.artifacts.insert_if_absent(artifact_hash, kind, size, "application/json", stored_size_bytes=300)


def test_an_artifact_is_recorded_once(stores, clock):
    first = _record(stores)
    assert first.created
    assert (first.artifact.artifact_hash, first.artifact.kind, first.artifact.size_bytes, first.artifact.stored_size_bytes, first.artifact.created_at) == (SCENE, "scene", 1200, 300, START)
    clock.advance(60)
    again = _record(stores)
    assert not again.created
    assert (again.artifact.created_at, again.artifact.last_used_at) == (START, clock.now)
    assert stores.artifacts.get(SCENE) == again.artifact
    assert stores.artifacts.get(TRAJECTORIES) is None


def test_one_hash_one_content(stores):
    _record(stores)
    with pytest.raises(ArtifactMismatch):
        _record(stores, size=1201)
    with pytest.raises(ValueError):
        _record(stores, artifact_hash=SCENE.upper())


def test_references_are_added_and_removed_once(stores, campaign):
    _record(stores)
    assert stores.artifacts.add_reference(SCENE, CASE, 17, "scene", campaign_id=campaign.campaign_id)
    assert not stores.artifacts.add_reference(SCENE, CASE, "17", "scene", campaign_id=campaign.campaign_id)
    assert stores.artifacts.add_reference(SCENE, ArtifactHolderKind.JOB, "job-1", "input")
    (by_case,) = stores.artifacts.references_of(CASE, 17)
    assert (by_case.artifact_hash, by_case.holder_id, by_case.role, by_case.campaign_id) == (SCENE, "17", "scene", campaign.campaign_id)
    assert [reference.holder_kind for reference in stores.artifacts.references(SCENE)] == [CASE, ArtifactHolderKind.JOB]
    assert stores.artifacts.remove_reference(SCENE, ArtifactHolderKind.JOB, "job-1", "input")
    assert not stores.artifacts.remove_reference(SCENE, ArtifactHolderKind.JOB, "job-1", "input")


def test_a_reference_needs_a_recorded_artifact(stores):
    with pytest.raises(UnknownArtifact):
        stores.artifacts.add_reference(SCENE, CASE, "1", "scene")


def test_removing_a_holders_references(stores):
    _record(stores)
    _record(stores, TRAJECTORIES, kind="trajectories")
    for artifact_hash, role in ((SCENE, "scene"), (TRAJECTORIES, "trajectories")):
        stores.artifacts.add_reference(artifact_hash, CASE, "5", role)
    stores.artifacts.add_reference(SCENE, CASE, "6", "scene")
    assert stores.artifacts.remove_references_of(CASE, "5", roles=["trajectories"]) == [TRAJECTORIES]
    assert stores.artifacts.remove_references_of(CASE, "5") == [SCENE]
    assert stores.artifacts.references_of(CASE, "5") == []
    assert len(stores.artifacts.references(SCENE)) == 1


def test_only_old_unreferenced_artifacts_are_swept(stores, clock):
    _record(stores)
    _record(stores, TRAJECTORIES, kind="trajectories")
    stores.artifacts.add_reference(SCENE, CASE, "5", "scene")
    # a fresh upload without a reference is spared until it has been unused for a while
    assert stores.artifacts.list_unreferenced(UNUSED_S) == []
    clock.advance(UNUSED_S)
    assert [artifact.artifact_hash for artifact in stores.artifacts.list_unreferenced(UNUSED_S)] == [TRAJECTORIES]
    # losing its last reference makes the scene unused from now on
    stores.artifacts.remove_references_of(CASE, "5")
    assert [artifact.artifact_hash for artifact in stores.artifacts.list_unreferenced(UNUSED_S)] == [TRAJECTORIES]
    clock.advance(UNUSED_S)
    # least recently used first
    assert [artifact.artifact_hash for artifact in stores.artifacts.list_unreferenced(UNUSED_S)] == [TRAJECTORIES, SCENE]
    assert [artifact.artifact_hash for artifact in stores.artifacts.list_unreferenced(UNUSED_S, limit=1)] == [TRAJECTORIES]


def test_delete_spares_artifacts_used_since_they_were_listed(stores, clock):
    _record(stores)
    _record(stores, TRAJECTORIES, kind="trajectories")
    clock.advance(UNUSED_S)
    listed = [artifact.artifact_hash for artifact in stores.artifacts.list_unreferenced(UNUSED_S)]
    stores.artifacts.add_reference(SCENE, CASE, "9", "scene")  # referenced after the listing
    assert stores.artifacts.delete_unreferenced(listed, UNUSED_S) == [TRAJECTORIES]
    assert stores.artifacts.get(TRAJECTORIES) is None and stores.artifacts.get(SCENE) is not None
    stores.artifacts.remove_references_of(CASE, "9")
    assert stores.artifacts.delete_unreferenced([SCENE], UNUSED_S) == []  # just used
    assert stores.artifacts.delete_unreferenced([], UNUSED_S) == []


def test_a_read_marks_the_artifact_used(stores, clock):
    _record(stores)
    clock.advance(UNUSED_S + 1)
    assert [record.artifact_hash for record in stores.artifacts.list_unreferenced(UNUSED_S)] == [SCENE]
    marked = stores.artifacts.mark_used(SCENE)
    assert marked.last_used_at == clock.now and marked.created_at == START
    assert stores.artifacts.list_unreferenced(UNUSED_S) == []
    assert stores.artifacts.delete_unreferenced([SCENE], UNUSED_S) == []
    assert stores.artifacts.mark_used(TRAJECTORIES) is None
