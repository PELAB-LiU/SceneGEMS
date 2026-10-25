import pytest

from scenegems_tool.cluster.protocol.routes import CA_CERTIFICATE_PATH, JOBS_PATH, NODE_CONTROL_PATH, PAIRING_PATH, bearer, credential_from_authorization


def test_paths_are_distinct_and_under_cluster():
    paths = [CA_CERTIFICATE_PATH, PAIRING_PATH, NODE_CONTROL_PATH, JOBS_PATH]
    assert len(set(paths)) == len(paths)
    assert all(path.startswith("/cluster/") for path in paths)


def test_bearer_round_trip():
    assert credential_from_authorization(bearer("node-1.secret")) == "node-1.secret"


@pytest.mark.parametrize("value", ["", "node-1.secret", "Basic abc", "bearer abc", None])
def test_non_bearer_values_give_no_credential(value):
    assert credential_from_authorization(value) == ""
