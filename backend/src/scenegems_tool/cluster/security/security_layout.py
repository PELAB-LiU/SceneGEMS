"""Where each file lives in a master's security folder.

master.json                      master id, addresses, broker account name and address
ca/ca_certificate.pem            trust anchor handed to nodes
ca/ca_key.pem                    CA key, owner-only, never mounted into a container
api/tls/server_*.pem             the master API's TLS certificate and key
broker/                          mounted read-only into the cluster broker
    nanomq.conf, nanomq_acl.conf
    tls/server_*.pem, tls/ca_certificate.pem
store/                           FileSecurityStore records (hashes only)
"""

from dataclasses import dataclass
from pathlib import Path

from scenegems_tool.cluster.security.broker.broker_config import ACCESS_RULES_FILE_NAME, CA_CERTIFICATE_FILE_NAME, CERTIFICATE_FILE_NAME, CONFIG_FILE_NAME, KEY_FILE_NAME, TLS_FOLDER_NAME


@dataclass(frozen=True)
class SecurityLayout:
    root: Path

    @property
    def master_file(self) -> Path:
        return self.root / "master.json"

    @property
    def ca_certificate(self) -> Path:
        return self.root / "ca" / "ca_certificate.pem"

    @property
    def ca_key(self) -> Path:
        return self.root / "ca" / "ca_key.pem"

    @property
    def api_certificate(self) -> Path:
        return self.root / "api" / TLS_FOLDER_NAME / CERTIFICATE_FILE_NAME

    @property
    def api_key(self) -> Path:
        return self.root / "api" / TLS_FOLDER_NAME / KEY_FILE_NAME

    @property
    def broker_folder(self) -> Path:
        return self.root / "broker"

    @property
    def broker_config(self) -> Path:
        return self.broker_folder / CONFIG_FILE_NAME

    @property
    def broker_access_rules(self) -> Path:
        return self.broker_folder / ACCESS_RULES_FILE_NAME

    @property
    def broker_certificate(self) -> Path:
        return self.broker_folder / TLS_FOLDER_NAME / CERTIFICATE_FILE_NAME

    @property
    def broker_key(self) -> Path:
        return self.broker_folder / TLS_FOLDER_NAME / KEY_FILE_NAME

    @property
    def broker_ca_certificate(self) -> Path:
        return self.broker_folder / TLS_FOLDER_NAME / CA_CERTIFICATE_FILE_NAME

    @property
    def store_folder(self) -> Path:
        return self.root / "store"
