"""A master's security folder: created at install time, loaded by the master at start.

`initialize_master_security` is safe to run again. It keeps the CA (nodes already trust
it) and the master id, and reissues the server certificates, so adding an address to the
master only needs another run. It refuses to change the master id of an existing folder.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from scenegems_tool.cluster.security.broker.access_rules import cluster_access_rules, render_access_rules
from scenegems_tool.cluster.security.broker.broker_config import TLS_PORT, ClusterBrokerSettings, render_broker_config
from scenegems_tool.cluster.security.certificates.certificate_authority import CertificateAuthority
from scenegems_tool.cluster.security.certificates.subject_names import subject_alternative_names
from scenegems_tool.cluster.security.credentials.broker_accounts import set_master_broker_account
from scenegems_tool.cluster.security.file_writing import write_private_file, write_public_file
from scenegems_tool.cluster.security.scope_names import ensure_scope_name
from scenegems_tool.cluster.security.security_layout import SecurityLayout
from scenegems_tool.cluster.security.store.file_security_store import FileSecurityStore
from scenegems_tool.cluster.security.store.security_store import SecurityStore


@dataclass(frozen=True)
class MasterIdentity:
    master_id: str
    addresses: Sequence[str]  # IP addresses and host names of the master, in its certificates
    master_broker_username: str
    broker_public_host: str  # the address nodes dial for the broker
    broker_public_port: int = TLS_PORT

    def to_json(self) -> str:
        return json.dumps(
            {
                "master_id": self.master_id,
                "addresses": list(self.addresses),
                "master_broker_username": self.master_broker_username,
                "broker_public_host": self.broker_public_host,
                "broker_public_port": self.broker_public_port,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> "MasterIdentity":
        values = json.loads(text)
        return cls(
            master_id=values["master_id"],
            addresses=tuple(values["addresses"]),
            master_broker_username=values["master_broker_username"],
            broker_public_host=values["broker_public_host"],
            broker_public_port=int(values["broker_public_port"]),
        )


@dataclass
class MasterSecurity:
    layout: SecurityLayout
    identity: MasterIdentity
    store: SecurityStore = field(repr=False)

    @property
    def master_id(self) -> str:
        return self.identity.master_id

    @property
    def ca_certificate_pem(self) -> str:
        return self.layout.ca_certificate.read_text(encoding="ascii")

    @classmethod
    def load(cls, root: Path, *, store: Optional[SecurityStore] = None) -> "MasterSecurity":
        layout = SecurityLayout(Path(root))
        if not layout.master_file.is_file():
            raise FileNotFoundError(f"No master security folder at {layout.root}; run `python -m scenegems_tool.cluster.security init` first")
        identity = MasterIdentity.from_json(layout.master_file.read_text(encoding="utf-8"))
        return cls(layout=layout, identity=identity, store=store or FileSecurityStore(layout.store_folder))


def initialize_master_security(
    root: Path,
    *,
    master_id: str,
    addresses: Sequence[str],
    master_broker_username: str,
    master_broker_password: str,
    broker: ClusterBrokerSettings,
    broker_public_host: Optional[str] = None,
    broker_public_port: int = TLS_PORT,
    store: Optional[SecurityStore] = None,
) -> MasterSecurity:
    layout = SecurityLayout(Path(root))
    ensure_scope_name(master_id, "master id")
    ensure_scope_name(master_broker_username, "master broker username")
    subject_alternative_names(addresses)  # fails early on a malformed address
    if layout.master_file.is_file():
        existing = MasterIdentity.from_json(layout.master_file.read_text(encoding="utf-8"))
        if existing.master_id != master_id:
            raise ValueError(f"{layout.root} belongs to master {existing.master_id!r}, not {master_id!r}; use another folder for another master")
    if not addresses and broker_public_host is None:
        raise ValueError("Give at least one master address (IP address or host name) that nodes can reach")
    broker_public_host = broker_public_host or addresses[0]
    identity = MasterIdentity(
        master_id=master_id,
        addresses=tuple(dict.fromkeys([*addresses, broker_public_host])),
        master_broker_username=master_broker_username,
        broker_public_host=broker_public_host,
        broker_public_port=broker_public_port,
    )

    if layout.ca_certificate.is_file() and layout.ca_key.is_file():
        authority = CertificateAuthority.load(layout.ca_certificate, layout.ca_key)
    else:
        authority = CertificateAuthority.create(master_id)
        authority.save(layout.ca_certificate, layout.ca_key)

    api_certificate = authority.issue_server_certificate(f"SceneGEMS master {master_id} API", identity.addresses)
    write_private_file(layout.api_key, api_certificate.private_key_pem)
    write_public_file(layout.api_certificate, api_certificate.certificate_pem)
    broker_certificate = authority.issue_server_certificate(f"SceneGEMS master {master_id} broker", identity.addresses)
    write_private_file(layout.broker_key, broker_certificate.private_key_pem)
    write_public_file(layout.broker_certificate, broker_certificate.certificate_pem)
    write_public_file(layout.broker_ca_certificate, authority.certificate_pem)

    # The broker configuration holds the hook secret, so it is written owner-only too.
    write_private_file(layout.broker_config, render_broker_config(broker).encode("utf-8"))
    write_public_file(layout.broker_access_rules, render_access_rules(cluster_access_rules(master_id, master_broker_username)).encode("utf-8"))

    security = MasterSecurity(layout=layout, identity=identity, store=store or FileSecurityStore(layout.store_folder))
    set_master_broker_account(security.store, master_broker_username, master_broker_password)
    write_public_file(layout.master_file, identity.to_json().encode("utf-8"))
    return security
