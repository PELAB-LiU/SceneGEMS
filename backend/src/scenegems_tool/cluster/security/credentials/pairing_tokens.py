"""One-time pairing tokens.

The operator creates a token on the master and gives it to the new node's installer. The
token is shown once, stored only as its SHA-256, expires after a short time and is
consumed by the first pairing request that presents it, valid or late.
"""

import datetime
from dataclasses import dataclass
from typing import Optional

from scenegems_tool.cluster.security.credentials.secret_hashing import new_secret, token_lookup_key
from scenegems_tool.cluster.security.store.security_store import PairingTokenRecord, SecurityStore

DEFAULT_TOKEN_LIFETIME = datetime.timedelta(minutes=30)
MAX_TOKEN_LIFETIME = datetime.timedelta(days=7)


class PairingTokenRejected(ValueError):
    """The token is unknown, already used or expired. The message never contains the token."""


@dataclass(frozen=True)
class CreatedPairingToken:
    token: str  # show to the operator once, never store or log
    expires_at: datetime.datetime

    def __repr__(self) -> str:
        return f"CreatedPairingToken(token=<hidden>, expires_at={self.expires_at.isoformat()})"


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def create_pairing_token(
    store: SecurityStore,
    *,
    lifetime: datetime.timedelta = DEFAULT_TOKEN_LIFETIME,
    note: str = "",
    now: Optional[datetime.datetime] = None,
) -> CreatedPairingToken:
    if not datetime.timedelta(0) < lifetime <= MAX_TOKEN_LIFETIME:
        raise ValueError(f"A pairing token lifetime must be positive and at most {MAX_TOKEN_LIFETIME}")
    now = now or _utc_now()
    token = new_secret()
    expires_at = now + lifetime
    store.add_pairing_token(PairingTokenRecord(token_lookup_key=token_lookup_key(token), created_at=now, expires_at=expires_at, note=note))
    return CreatedPairingToken(token=token, expires_at=expires_at)


def consume_pairing_token(store: SecurityStore, token: str, *, now: Optional[datetime.datetime] = None) -> PairingTokenRecord:
    """Use the token up. Raises PairingTokenRejected when it cannot pair a node."""
    record = store.take_pairing_token(token_lookup_key(token)) if token else None
    if record is None:
        raise PairingTokenRejected("Unknown or already used pairing token")
    if (now or _utc_now()) >= record.expires_at:
        raise PairingTokenRejected("Pairing token expired; create a new one on the master")
    return record


def purge_expired_pairing_tokens(store: SecurityStore, *, now: Optional[datetime.datetime] = None) -> int:
    now = now or _utc_now()
    removed = 0
    for record in store.list_pairing_tokens():
        if now >= record.expires_at and store.take_pairing_token(record.token_lookup_key) is not None:
            removed += 1
    return removed
