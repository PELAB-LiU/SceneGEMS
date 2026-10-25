from datetime import timedelta

import pytest

from scenegems_tool.cluster.security.scope_names import InvalidScopeName
from scenegems_tool.cluster.security.store.file_security_store import FileSecurityStore
from scenegems_tool.cluster.security.store.security_store import BrokerAccountRecord, NodeCredentialRecord, PairingTokenRecord, RecordExists

TOKEN_KEY = "a" * 64


def _token(instant, key=TOKEN_KEY):
    return PairingTokenRecord(token_lookup_key=key, created_at=instant, expires_at=instant + timedelta(minutes=30), note="lab-1")


def test_pairing_token_is_taken_once(store, instant):
    store.add_pairing_token(_token(instant))
    assert store.list_pairing_tokens() == [_token(instant)]
    assert store.take_pairing_token(TOKEN_KEY) == _token(instant)
    assert store.take_pairing_token(TOKEN_KEY) is None
    assert store.list_pairing_tokens() == []


def test_pairing_token_keys_are_hex_digests_only(store, instant):
    with pytest.raises(ValueError):
        store.take_pairing_token("../node_credentials/x")
    with pytest.raises(ValueError):
        store.add_pairing_token(_token(instant, key="A" * 64))


def test_node_credential_round_trip_and_uniqueness(store, instant):
    record = NodeCredentialRecord(node_id="lab-1-a1b2c3", node_name="lab 1", credential_hash="scrypt$x", created_at=instant, labels={"gpu": "no"})
    store.add_node_credential(record)
    assert store.get_node_credential("lab-1-a1b2c3") == record
    with pytest.raises(RecordExists):
        store.add_node_credential(record)
    assert store.remove_node_credential("lab-1-a1b2c3")
    assert store.get_node_credential("lab-1-a1b2c3") is None


def test_broker_account_put_replace_and_remove(store, instant):
    record = BrokerAccountRecord(username="master", password_hash="scrypt$1", role="master", created_at=instant)
    store.put_broker_account(record)
    with pytest.raises(RecordExists):
        store.put_broker_account(record)
    replaced = BrokerAccountRecord(username="master", password_hash="scrypt$2", role="master", created_at=instant)
    store.put_broker_account(replaced, replace=True)
    assert store.get_broker_account("master") == replaced
    assert store.remove_broker_account("master")
    assert store.get_broker_account("master") is None


@pytest.mark.parametrize("name", ["../x", "a/b", "A", "", "x" * 64])
def test_record_names_cannot_leave_their_folder(store, name):
    with pytest.raises(InvalidScopeName):
        store.get_node_credential(name)
    with pytest.raises(InvalidScopeName):
        store.get_broker_account(name)


def test_two_store_objects_on_one_folder_see_the_same_state(tmp_path, instant):
    first, second = FileSecurityStore(tmp_path / "store"), FileSecurityStore(tmp_path / "store")
    first.add_pairing_token(_token(instant))
    assert second.take_pairing_token(TOKEN_KEY) is not None
    assert first.take_pairing_token(TOKEN_KEY) is None


def test_empty_store_lists_nothing(tmp_path):
    assert FileSecurityStore(tmp_path / "missing").list_pairing_tokens() == []
