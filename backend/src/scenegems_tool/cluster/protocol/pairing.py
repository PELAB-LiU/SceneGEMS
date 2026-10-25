"""Pairing over the master's REST API: a one-time token becomes the node's credentials.

The operator creates the token on the master. The node sends it once and stores the
response in its volume; from then on it authenticates the control WebSocket with the
node credential and the broker with its own broker account.

Secret fields are left out of `repr`, so logging a model never prints a secret; they are
still part of the JSON on the wire.
"""

from typing import Dict, Optional

from pydantic import Field

from scenegems_tool.cluster.protocol.model_base import ProtocolFrame, ProtocolModel


class PairingRequest(ProtocolFrame):
    token: str = Field(repr=False)
    node_name: str
    labels: Dict[str, str] = Field(default_factory=dict)


class BrokerAccess(ProtocolModel):
    """The node's account on the master's MQTT broker, limited to its own topics."""

    host: str
    port: int = Field(ge=1, le=65535)
    username: str
    password: str = Field(repr=False)
    topic_scope: str  # the node's topic prefix; its subsystem instances publish under <topic_scope>/<instance_id>/
    tls: bool = True
    client_certificate_pem: Optional[str] = None
    client_key_pem: Optional[str] = Field(default=None, repr=False)


class PairingResponse(ProtocolFrame):
    master_id: str
    node_id: str
    node_credential: str = Field(repr=False)  # bearer secret for the control WebSocket and the REST API
    ca_certificate_pem: str  # trust anchor for the master's API and broker certificates
    broker: BrokerAccess
