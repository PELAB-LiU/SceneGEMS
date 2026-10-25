import pytest

from scenegems_tool.cluster.security.credentials.broker_accounts import (
    MASTER_ROLE,
    NODE_ROLE,
    create_node_broker_account,
    remove_broker_account,
    set_master_broker_account,
    verify_broker_login,
)
from scenegems_tool.cluster.security.store.security_store import RecordExists

MASTER_PASSWORD = "test-master-password-0001"


def test_node_account_is_named_after_the_node_and_logs_in(store):
    account = create_node_broker_account(store, "lab-1-a1b2c3")
    assert account.username == "lab-1-a1b2c3"
    assert store.get_broker_account("lab-1-a1b2c3").role == NODE_ROLE
    assert verify_broker_login(store, "lab-1-a1b2c3", account.password)
    assert account.password not in repr(account)


def test_wrong_password_unknown_user_and_empty_password_are_refused(store):
    account = create_node_broker_account(store, "lab-1-a1b2c3")
    assert not verify_broker_login(store, "lab-1-a1b2c3", account.password + "x")
    assert not verify_broker_login(store, "lab-1-a1b2c3", "")
    assert not verify_broker_login(store, "lab-2-000000", account.password)


@pytest.mark.parametrize("username", ["#", "+", "lab-1-a1b2c3/#", "", "../store", "Lab-1-A1B2C3"])
def test_usernames_outside_the_scope_name_rule_never_log_in(store, username):
    account = create_node_broker_account(store, "lab-1-a1b2c3")
    assert not verify_broker_login(store, username, account.password)


def test_master_account_uses_the_operator_password_and_can_be_replaced(store):
    set_master_broker_account(store, "master", MASTER_PASSWORD)
    assert store.get_broker_account("master").role == MASTER_ROLE
    assert verify_broker_login(store, "master", MASTER_PASSWORD)
    set_master_broker_account(store, "master", MASTER_PASSWORD + "-new")
    assert not verify_broker_login(store, "master", MASTER_PASSWORD)
    assert verify_broker_login(store, "master", MASTER_PASSWORD + "-new")


def test_master_password_must_be_long_enough(store):
    with pytest.raises(ValueError, match="at least 16"):
        set_master_broker_account(store, "master", "short")


def test_node_and_master_accounts_cannot_take_each_others_name(store):
    set_master_broker_account(store, "master", MASTER_PASSWORD)
    with pytest.raises(RecordExists):
        create_node_broker_account(store, "master")
    create_node_broker_account(store, "lab-1-a1b2c3")
    with pytest.raises(ValueError, match="belongs to a node"):
        set_master_broker_account(store, "lab-1-a1b2c3", MASTER_PASSWORD)


def test_removed_account_no_longer_logs_in(store):
    account = create_node_broker_account(store, "lab-1-a1b2c3")
    assert remove_broker_account(store, "lab-1-a1b2c3")
    assert not verify_broker_login(store, "lab-1-a1b2c3", account.password)
    assert not remove_broker_account(store, "lab-1-a1b2c3")
