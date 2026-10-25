"""SecurityStore on files: one JSON file per record under the master's security folder.

    <root>/pairing_tokens/<sha256 of the token>.json
    <root>/node_credentials/<node_id>.json
    <root>/broker_accounts/<username>.json

Several processes may use one folder (the master API and the command line). New records
are created exclusively and updates are atomic renames. A token is taken by first creating
its `.claim` file exclusively: only one of two racing takers can create it.
"""

import datetime
import json
import os
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from scenegems_tool.cluster.security.file_writing import write_private_file
from scenegems_tool.cluster.security.scope_names import ensure_scope_name
from scenegems_tool.cluster.security.store.security_store import BrokerAccountRecord, NodeCredentialRecord, PairingTokenRecord, RecordExists

_TOKEN_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_UNLINK_RETRIES = 40


def _encode(record: Any) -> bytes:
    values = asdict(record)
    for key, value in values.items():
        if isinstance(value, datetime.datetime):
            values[key] = value.isoformat()
    return json.dumps(values, sort_keys=True, indent=2).encode("utf-8")


def _decode_times(values: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    for key in keys:
        values[key] = datetime.datetime.fromisoformat(values[key])
    return values


def _create_exclusive(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RecordExists(f"{path.stem} already exists") from exc
    with os.fdopen(descriptor, "wb") as file:
        file.write(content)


def _unlink_with_retries(path: Path) -> None:
    for _ in range(_UNLINK_RETRIES):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            # Windows refuses to delete a file another thread or process is reading right now.
            time.sleep(0.05)
    path.unlink(missing_ok=True)


def _ensure_token_key(token_lookup_key: str) -> str:
    if not _TOKEN_KEY_PATTERN.fullmatch(token_lookup_key):
        raise ValueError("A pairing token lookup key is a lowercase SHA-256 hex digest")
    return token_lookup_key


class FileSecurityStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._tokens = self.root / "pairing_tokens"
        self._nodes = self.root / "node_credentials"
        self._accounts = self.root / "broker_accounts"

    # Pairing tokens

    def add_pairing_token(self, record: PairingTokenRecord) -> None:
        _create_exclusive(self._tokens / f"{_ensure_token_key(record.token_lookup_key)}.json", _encode(record))

    def take_pairing_token(self, token_lookup_key: str) -> Optional[PairingTokenRecord]:
        path = self._tokens / f"{_ensure_token_key(token_lookup_key)}.json"
        claim = path.with_suffix(".claim")
        # Exclusive creation is atomic on POSIX and NTFS; concurrent renames of one file are
        # not on Windows, where two of them can both report success.
        try:
            os.close(os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        except FileExistsError:
            return None
        except FileNotFoundError:
            return None  # no token folder yet
        try:
            try:
                values = json.loads(path.read_bytes())
            except FileNotFoundError:
                return None
            _unlink_with_retries(path)
        finally:
            # A claim left behind by a crash keeps its token unusable, which fails closed.
            _unlink_with_retries(claim)
        return PairingTokenRecord(**_decode_times(values, "created_at", "expires_at"))

    def list_pairing_tokens(self) -> list[PairingTokenRecord]:
        records = []
        for path in sorted(self._tokens.glob("*.json")) if self._tokens.is_dir() else []:
            try:
                values = json.loads(path.read_bytes())
            except (FileNotFoundError, PermissionError):
                continue  # taken while listing
            records.append(PairingTokenRecord(**_decode_times(values, "created_at", "expires_at")))
        return records

    # Node credentials

    def add_node_credential(self, record: NodeCredentialRecord) -> None:
        _create_exclusive(self._node_path(record.node_id), _encode(record))

    def get_node_credential(self, node_id: str) -> Optional[NodeCredentialRecord]:
        path = self._node_path(node_id)
        if not path.is_file():
            return None
        return NodeCredentialRecord(**_decode_times(json.loads(path.read_bytes()), "created_at"))

    def remove_node_credential(self, node_id: str) -> bool:
        return self._remove(self._node_path(node_id))

    # Broker accounts

    def put_broker_account(self, record: BrokerAccountRecord, *, replace: bool = False) -> None:
        path = self._account_path(record.username)
        if replace:
            write_private_file(path, _encode(record))
        else:
            _create_exclusive(path, _encode(record))

    def get_broker_account(self, username: str) -> Optional[BrokerAccountRecord]:
        path = self._account_path(username)
        if not path.is_file():
            return None
        return BrokerAccountRecord(**_decode_times(json.loads(path.read_bytes()), "created_at"))

    def remove_broker_account(self, username: str) -> bool:
        return self._remove(self._account_path(username))

    def _node_path(self, node_id: str) -> Path:
        return self._nodes / f"{ensure_scope_name(node_id, 'node id')}.json"

    def _account_path(self, username: str) -> Path:
        return self._accounts / f"{ensure_scope_name(username, 'broker username')}.json"

    @staticmethod
    def _remove(path: Path) -> bool:
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
