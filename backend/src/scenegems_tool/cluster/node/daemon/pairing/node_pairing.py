"""Pair on first start, reuse the stored pairing afterwards.

First start: fetch the CA unverified, check it against the pinned hash, send the token
over HTTPS verified against that CA, check that the answer names the configured master
and the same CA, then store it. Later starts load the stored pairing and need no token.
A stored pairing for another master or another CA is refused rather than replaced, since
replacing it would need a new token anyway.
"""

import logging
from typing import Callable

from scenegems_tool.cluster.node.daemon.configuration.node_configuration import NodeConfiguration
from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import CaPinMismatch, certificate_sha256, pinned_ca_certificate, verified_context
from scenegems_tool.cluster.node.daemon.pairing.pairing_client import request_pairing
from scenegems_tool.cluster.node.daemon.pairing.pairing_state import PairingState, PairingStateError, StoredPairing, write_trust_folder
from scenegems_tool.cluster.protocol.pairing import PairingRequest, PairingResponse

_logger = logging.getLogger(__name__)

PairingCall = Callable[[NodeConfiguration], PairingResponse]


class NotPaired(RuntimeError):
    """The node has no pairing yet and no token to get one."""


def pair_with_master(configuration: NodeConfiguration) -> PairingResponse:
    """The network part of the first start: pinned CA, then the token over verified HTTPS."""
    ca_certificate_pem = pinned_ca_certificate(configuration.master_url, configuration.master_ca_sha256)
    request = PairingRequest(token=configuration.pairing_token or "", node_name=configuration.node_name, labels=configuration.labels)
    return request_pairing(configuration.master_url, verified_context(ca_certificate_pem), request)


def ensure_paired(configuration: NodeConfiguration, *, pair: PairingCall = pair_with_master) -> StoredPairing:
    state = PairingState(configuration.state_dir)
    stored = state.load()
    if stored is None:
        if not configuration.pairing_token:
            raise NotPaired(f"The node is not paired yet ({state.pairing_file} does not exist) and SCENEGEMS_PAIRING_TOKEN is not set. Create a token on the master.")
        _logger.info("Pairing node %s with master %s at %s", configuration.node_name, configuration.master_id, configuration.master_url)
        response = pair(configuration)
        check_response(configuration, response)
        stored = state.save(configuration.master_url, configuration.master_ca_sha256, response)
        _logger.info("Paired as node %s of master %s; the pairing token is no longer needed", response.node_id, response.master_id)
    else:
        check_stored(configuration, stored)
        state.write_ca_certificate(stored.response)
    write_trust_folder(configuration.trust_dir, stored.response)
    return stored


def check_response(configuration: NodeConfiguration, response: PairingResponse) -> None:
    if response.master_id != configuration.master_id:
        raise PairingStateError(f"The master at {configuration.master_url} is {response.master_id!r}, not SCENEGEMS_MASTER_ID {configuration.master_id!r}; nothing was stored")
    if certificate_sha256(response.ca_certificate_pem) != configuration.master_ca_sha256:
        raise CaPinMismatch("The pairing answer carries another CA certificate than the pinned one; nothing was stored")


def check_stored(configuration: NodeConfiguration, stored: StoredPairing) -> None:
    if stored.response.master_id != configuration.master_id:
        raise PairingStateError(
            f"The state folder {configuration.state_dir} belongs to master {stored.response.master_id!r}, not {configuration.master_id!r}. Use another state volume for another master."
        )
    if stored.master_ca_sha256 != configuration.master_ca_sha256 or certificate_sha256(stored.response.ca_certificate_pem) != configuration.master_ca_sha256:
        raise PairingStateError(
            f"The node was paired with a master whose CA hash is {stored.master_ca_sha256}, but SCENEGEMS_MASTER_CA_SHA256 is {configuration.master_ca_sha256}. "
            "Remove the node's state volume and pair again with a new token."
        )
    if stored.master_url != configuration.master_url:
        _logger.warning("SCENEGEMS_MASTER_URL changed from %s to %s since pairing; connecting to the new address", stored.master_url, configuration.master_url)
