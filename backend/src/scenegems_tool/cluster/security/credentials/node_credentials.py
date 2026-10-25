"""The node's credential: one bearer secret for the master's REST API and control WebSocket.

The credential reads `<node_id>.<secret>`, so a single header names the node and proves
it. The master stores only the secret's hash next to the node id.
"""

import datetime
from dataclasses import dataclass
from typing import Mapping, Optional

from scenegems_tool.cluster.security.credentials.secret_hashing import hash_secret, new_secret, verify_secret
from scenegems_tool.cluster.security.scope_names import ensure_scope_name, is_scope_name
from scenegems_tool.cluster.security.store.security_store import NodeCredentialRecord, SecurityStore

_SEPARATOR = "."


@dataclass(frozen=True)
class IssuedNodeCredential:
    node_id: str
    credential: str  # handed to the node once, never stored or logged

    def __repr__(self) -> str:
        return f"IssuedNodeCredential(node_id={self.node_id!r}, credential=<hidden>)"


def issue_node_credential(
    store: SecurityStore,
    node_id: str,
    node_name: str,
    *,
    labels: Optional[Mapping[str, str]] = None,
    now: Optional[datetime.datetime] = None,
) -> IssuedNodeCredential:
    """Raises RecordExists when the node id is already paired."""
    ensure_scope_name(node_id, "node id")
    secret = new_secret()
    store.add_node_credential(
        NodeCredentialRecord(
            node_id=node_id,
            node_name=node_name,
            credential_hash=hash_secret(secret),
            created_at=now or datetime.datetime.now(datetime.timezone.utc),
            labels=dict(labels or {}),
        )
    )
    return IssuedNodeCredential(node_id=node_id, credential=f"{node_id}{_SEPARATOR}{secret}")


def authenticate_node(store: SecurityStore, credential: str) -> Optional[str]:
    """The node id the credential belongs to, or None when it is not valid."""
    node_id, separator, secret = (credential or "").partition(_SEPARATOR)
    if not separator or not secret or not is_scope_name(node_id):
        return None
    record = store.get_node_credential(node_id)
    if record is None or not verify_secret(secret, record.credential_hash):
        return None
    return node_id


def revoke_node_credential(store: SecurityStore, node_id: str) -> bool:
    return store.remove_node_credential(node_id)
