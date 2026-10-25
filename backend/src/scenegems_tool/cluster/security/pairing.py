"""Pairing: a node exchanges a one-time token for its credentials.

P3.3's REST route calls `pair_node` with the decoded PairingRequest and returns the
PairingResponse to the node, which stores it in its volume. A rejected token raises
PairingTokenRejected (answer 403); nothing about the token is echoed back.
"""

import datetime
import secrets
from typing import Optional

from scenegems_tool.cluster.protocol.pairing import BrokerAccess, PairingRequest, PairingResponse
from scenegems_tool.cluster.security.broker.access_rules import node_topic_scope
from scenegems_tool.cluster.security.credentials.broker_accounts import create_node_broker_account
from scenegems_tool.cluster.security.credentials.node_credentials import issue_node_credential, revoke_node_credential
from scenegems_tool.cluster.security.credentials.pairing_tokens import PairingTokenRejected, consume_pairing_token
from scenegems_tool.cluster.security.master_security import MasterSecurity
from scenegems_tool.cluster.security.scope_names import slug_from_name
from scenegems_tool.cluster.security.store.security_store import RecordExists

__all__ = ["PairingTokenRejected", "new_node_id", "pair_node"]

_NODE_ID_ATTEMPTS = 8


def new_node_id(node_name: str) -> str:
    """`<slug of the name>-<6 hex digits>`: readable in container names, unique in practice."""
    return f"{slug_from_name(node_name)}-{secrets.token_hex(3)}"


def pair_node(security: MasterSecurity, request: PairingRequest, *, now: Optional[datetime.datetime] = None) -> PairingResponse:
    consume_pairing_token(security.store, request.token, now=now)
    store = security.store
    for _ in range(_NODE_ID_ATTEMPTS):
        node_id = new_node_id(request.node_name)
        if node_id == security.identity.master_broker_username:
            continue
        try:
            credential = issue_node_credential(store, node_id, request.node_name, labels=request.labels, now=now)
        except RecordExists:
            continue
        try:
            broker_account = create_node_broker_account(store, node_id, now=now)
        except RecordExists:
            revoke_node_credential(store, node_id)
            continue
        break
    else:
        raise RuntimeError("Could not find a free node id; try pairing again")

    return PairingResponse(
        master_id=security.master_id,
        node_id=node_id,
        node_credential=credential.credential,
        ca_certificate_pem=security.ca_certificate_pem,
        broker=BrokerAccess(
            host=security.identity.broker_public_host,
            port=security.identity.broker_public_port,
            username=broker_account.username,
            password=broker_account.password,
            topic_scope=node_topic_scope(security.master_id, node_id),
            tls=True,
        ),
    )
