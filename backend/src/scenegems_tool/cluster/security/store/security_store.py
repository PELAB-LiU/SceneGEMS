"""The records of the master's security state and the interface that stores them.

The interface is small on purpose: a database implementation needs one table per record
type, and `take_pairing_token` maps to `DELETE ... RETURNING`, which is what makes a
token usable only once even when two pairing requests race.
"""

import datetime
from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol


class RecordExists(ValueError):
    """Raised when a record with the same key is already stored."""


@dataclass(frozen=True)
class PairingTokenRecord:
    token_lookup_key: str  # SHA-256 of the token, never the token itself
    created_at: datetime.datetime
    expires_at: datetime.datetime
    note: str = ""


@dataclass(frozen=True)
class NodeCredentialRecord:
    node_id: str
    node_name: str
    credential_hash: str
    created_at: datetime.datetime
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BrokerAccountRecord:
    username: str
    password_hash: str
    role: str  # "master" or "node"
    created_at: datetime.datetime


class SecurityStore(Protocol):
    def add_pairing_token(self, record: PairingTokenRecord) -> None: ...

    def take_pairing_token(self, token_lookup_key: str) -> Optional[PairingTokenRecord]:
        """Remove and return the token record; None when it does not exist or was taken already."""
        ...

    def list_pairing_tokens(self) -> list[PairingTokenRecord]: ...

    def add_node_credential(self, record: NodeCredentialRecord) -> None:
        """Raises RecordExists when the node id is taken."""
        ...

    def get_node_credential(self, node_id: str) -> Optional[NodeCredentialRecord]: ...

    def remove_node_credential(self, node_id: str) -> bool: ...

    def put_broker_account(self, record: BrokerAccountRecord, *, replace: bool = False) -> None:
        """Raises RecordExists when the username is taken and `replace` is false."""
        ...

    def get_broker_account(self, username: str) -> Optional[BrokerAccountRecord]: ...

    def remove_broker_account(self, username: str) -> bool: ...
