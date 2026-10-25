"""The master's CA certificate inside a subsystem container, for TLS to the cluster broker.

A container started by the node daemon runs next to the daemon, not inside it, so a file
in the daemon's own folder does not exist there. The daemon keeps the CA file in a trust
folder that Docker can mount: a named volume (the node's compose project creates one) or
a host folder. The launcher mounts that folder read-only at TRUST_FOLDER_IN_CONTAINER and
points MQTT_CA_CERTIFICATE at the file there.
"""

import re
from dataclasses import dataclass

TRUST_FOLDER_IN_CONTAINER = "/etc/scenegems/trust"
CA_CERTIFICATE_FILE_NAME = "ca_certificate.pem"
_VOLUME_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")  # Docker's rule for volume names; a host folder has '/' or ':'


@dataclass(frozen=True)
class CaCertificateMount:
    source: str  # Docker volume name or absolute host folder that holds CA_CERTIFICATE_FILE_NAME

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("The CA certificate mount needs a volume name or a host folder")

    @property
    def is_volume(self) -> bool:
        return _VOLUME_NAME.match(self.source) is not None

    @property
    def certificate_path(self) -> str:
        """Where the container finds the CA file; the value of MQTT_CA_CERTIFICATE."""
        return f"{TRUST_FOLDER_IN_CONTAINER}/{CA_CERTIFICATE_FILE_NAME}"

    def apply(self, compose: dict, service_key: str) -> dict:
        """Mount the trust folder into one service and point its broker client at the CA file."""
        service = compose["services"][service_key]
        service.setdefault("volumes", []).append(f"{self.source}:{TRUST_FOLDER_IN_CONTAINER}:ro")
        service.setdefault("environment", {})["MQTT_CA_CERTIFICATE"] = self.certificate_path
        if self.is_volume:
            compose.setdefault("volumes", {})[self.source] = {"external": True, "name": self.source}
        return compose
