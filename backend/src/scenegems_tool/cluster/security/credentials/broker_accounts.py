"""Accounts on the master's MQTT broker.

There are two roles. The master account may use the whole cluster topic tree, a node
account only its own scope (see broker/access_rules.py). A node account's username is
the node id, which is what lets one static access rule with the `${username}` placeholder
cover every node, so pairing a node never changes the broker's rules.

The broker asks the master to check each login (broker/auth_hook.py), so the broker
never holds a password and new accounts work without restarting it.
"""

import datetime
from dataclasses import dataclass
from typing import Optional

from scenegems_tool.cluster.security.credentials.secret_hashing import hash_secret, new_secret, verify_secret
from scenegems_tool.cluster.security.scope_names import ensure_scope_name, is_scope_name
from scenegems_tool.cluster.security.store.security_store import BrokerAccountRecord, SecurityStore

MASTER_ROLE = "master"
NODE_ROLE = "node"
MIN_MASTER_PASSWORD_LENGTH = 16


@dataclass(frozen=True)
class IssuedBrokerAccount:
    username: str
    password: str  # handed to the account holder once, never stored or logged

    def __repr__(self) -> str:
        return f"IssuedBrokerAccount(username={self.username!r}, password=<hidden>)"


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def set_master_broker_account(store: SecurityStore, username: str, password: str, *, now: Optional[datetime.datetime] = None) -> None:
    """Create or replace the master's own account with an operator-chosen password (from .env)."""
    ensure_scope_name(username, "master broker username")
    if len(password) < MIN_MASTER_PASSWORD_LENGTH:
        raise ValueError(f"The master broker password must have at least {MIN_MASTER_PASSWORD_LENGTH} characters")
    existing = store.get_broker_account(username)
    if existing is not None and existing.role != MASTER_ROLE:
        raise ValueError(f"Broker username {username!r} already belongs to a node")
    store.put_broker_account(BrokerAccountRecord(username=username, password_hash=hash_secret(password), role=MASTER_ROLE, created_at=now or _utc_now()), replace=True)


def create_node_broker_account(store: SecurityStore, node_id: str, *, now: Optional[datetime.datetime] = None) -> IssuedBrokerAccount:
    """A new account named after the node, with a generated password. Raises RecordExists when taken."""
    ensure_scope_name(node_id, "node id")
    password = new_secret()
    store.put_broker_account(BrokerAccountRecord(username=node_id, password_hash=hash_secret(password), role=NODE_ROLE, created_at=now or _utc_now()))
    return IssuedBrokerAccount(username=node_id, password=password)


def verify_broker_login(store: SecurityStore, username: str, password: str) -> bool:
    """The broker's login check. Usernames outside the scope name rule never log in."""
    if not is_scope_name(username) or not password:
        return False
    record = store.get_broker_account(username)
    return record is not None and verify_secret(password, record.password_hash)


def remove_broker_account(store: SecurityStore, username: str) -> bool:
    """New logins fail at once; an open connection stays until it reconnects."""
    return store.remove_broker_account(username)
