"""The pairing result in the node's state folder, kept across restarts.

    pairing.json         the PairingResponse (node credential, broker account, CA) and the
                         master URL and CA hash it was paired with; owner-only
    ca_certificate.pem   the master's CA certificate, for this process's TLS clients

The trust folder gets its own copy of the CA file, which job containers mount; it holds
no secret, so the state folder itself is never mounted into a job container.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from scenegems_tool.cluster.node.daemon.pairing.pairing_client import decode_pairing_response
from scenegems_tool.cluster.node.launchers.ca_certificate_mount import CA_CERTIFICATE_FILE_NAME
from scenegems_tool.cluster.protocol.pairing import PairingResponse
from scenegems_tool.cluster.security.file_writing import write_private_file, write_public_file

PAIRING_FILE_NAME = "pairing.json"


class PairingStateError(RuntimeError):
    """The state folder holds a pairing that does not fit the configuration, or cannot be read."""


@dataclass(frozen=True)
class StoredPairing:
    master_url: str
    master_ca_sha256: str
    paired_at: str
    response: PairingResponse


@dataclass(frozen=True)
class PairingState:
    folder: Path

    @property
    def pairing_file(self) -> Path:
        return Path(self.folder) / PAIRING_FILE_NAME

    @property
    def ca_certificate_file(self) -> Path:
        return Path(self.folder) / CA_CERTIFICATE_FILE_NAME

    def load(self) -> Optional[StoredPairing]:
        if not self.pairing_file.is_file():
            return None
        try:
            document = json.loads(self.pairing_file.read_text(encoding="utf-8"))
            response = decode_pairing_response(json.dumps(document["response"]).encode("utf-8"))
            return StoredPairing(master_url=document["master_url"], master_ca_sha256=document["master_ca_sha256"], paired_at=document["paired_at"], response=response)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            raise PairingStateError(f"Cannot read the pairing state {self.pairing_file}: {error}. Remove the node's state volume to pair again.") from error

    def save(self, master_url: str, master_ca_sha256: str, response: PairingResponse) -> StoredPairing:
        stored = StoredPairing(master_url=master_url, master_ca_sha256=master_ca_sha256, paired_at=datetime.now(timezone.utc).isoformat(), response=response)
        Path(self.folder).mkdir(parents=True, exist_ok=True)
        _restrict_folder(Path(self.folder))
        document = {
            "master_url": stored.master_url,
            "master_ca_sha256": stored.master_ca_sha256,
            "paired_at": stored.paired_at,
            "response": response.model_dump(mode="json"),  # secrets included: repr hides them, the dump does not
        }
        write_private_file(self.pairing_file, json.dumps(document, indent=2).encode("utf-8"))
        self.write_ca_certificate(response)
        return stored

    def write_ca_certificate(self, response: PairingResponse) -> Path:
        write_public_file(self.ca_certificate_file, response.ca_certificate_pem.encode("ascii"))
        return self.ca_certificate_file


def write_trust_folder(trust_dir: Path, response: PairingResponse) -> Path:
    """Write the CA file job containers mount; rewritten at every start, so it always matches the pairing."""
    path = Path(trust_dir) / CA_CERTIFICATE_FILE_NAME
    write_public_file(path, response.ca_certificate_pem.encode("ascii"))
    return path


def _restrict_folder(folder: Path) -> None:
    if os.name == "posix":
        os.chmod(folder, 0o700)
