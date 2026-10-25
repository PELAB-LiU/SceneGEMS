import pytest

from scenegems_tool.cluster.security.credentials.node_credentials import authenticate_node, issue_node_credential, revoke_node_credential
from scenegems_tool.cluster.security.scope_names import InvalidScopeName
from scenegems_tool.cluster.security.store.security_store import RecordExists


def test_issued_credential_authenticates_its_node(store, instant):
    issued = issue_node_credential(store, "lab-1-a1b2c3", "lab 1", labels={"gpu": "no"}, now=instant)
    assert issued.credential.startswith("lab-1-a1b2c3.")
    assert authenticate_node(store, issued.credential) == "lab-1-a1b2c3"
    record = store.get_node_credential("lab-1-a1b2c3")
    assert record.labels == {"gpu": "no"} and record.created_at == instant


def test_store_holds_only_a_hash(store, tmp_path):
    issued = issue_node_credential(store, "lab-1-a1b2c3", "lab 1")
    secret = issued.credential.partition(".")[2]
    content = (tmp_path / "store" / "node_credentials" / "lab-1-a1b2c3.json").read_text()
    assert secret not in content
    assert secret not in repr(issued)


@pytest.mark.parametrize(
    "credential",
    [
        "",
        "lab-1-a1b2c3",
        "lab-1-a1b2c3.",
        "lab-1-a1b2c3.wrong-secret",
        "other-node.{secret}",
        "../lab-1-a1b2c3.{secret}",
        "LAB-1-A1B2C3.{secret}",
    ],
)
def test_invalid_credentials_are_refused(store, credential):
    issued = issue_node_credential(store, "lab-1-a1b2c3", "lab 1")
    issue_node_credential(store, "other-node", "other")
    secret = issued.credential.partition(".")[2]
    assert authenticate_node(store, credential.format(secret=secret)) is None


def test_node_id_is_unique(store):
    issue_node_credential(store, "lab-1-a1b2c3", "lab 1")
    with pytest.raises(RecordExists):
        issue_node_credential(store, "lab-1-a1b2c3", "lab 1 again")


def test_node_id_follows_the_scope_name_rule(store):
    with pytest.raises(InvalidScopeName):
        issue_node_credential(store, "lab/1", "lab 1")


def test_revoked_credential_no_longer_authenticates(store):
    issued = issue_node_credential(store, "lab-1-a1b2c3", "lab 1")
    assert revoke_node_credential(store, "lab-1-a1b2c3")
    assert authenticate_node(store, issued.credential) is None
    assert not revoke_node_credential(store, "lab-1-a1b2c3")
