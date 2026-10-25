"""The pairing request: the one-time token for the node's credentials, over HTTPS verified against the pinned CA."""

import json
import ssl
import urllib.error
import urllib.request

from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import open_url
from scenegems_tool.cluster.protocol.pairing import PairingRequest, PairingResponse
from scenegems_tool.cluster.protocol.routes import PAIRING_PATH
from scenegems_tool.cluster.protocol.version import ensure_compatible

PAIRING_TIMEOUT_S = 30.0


class PairingRefused(RuntimeError):
    """The master refused the pairing request, for example because the token is used up or expired."""


def request_pairing(master_url: str, context: ssl.SSLContext, request: PairingRequest, *, timeout_s: float = PAIRING_TIMEOUT_S) -> PairingResponse:
    http_request = urllib.request.Request(
        f"{master_url}{PAIRING_PATH}",
        data=request.model_dump_json().encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with open_url(http_request, context, timeout_s) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        detail = _error_detail(error)
        if error.code in (401, 403):
            raise PairingRefused(f"The master refused the pairing token (HTTP {error.code}{detail}). Create a new token on the master and set SCENEGEMS_PAIRING_TOKEN.") from error
        raise PairingRefused(f"The master answered the pairing request with HTTP {error.code}{detail}") from error
    return decode_pairing_response(body)


def decode_pairing_response(body: bytes) -> PairingResponse:
    """The response, version checked first, so a master of another revision fails with the version error."""
    try:
        data = json.loads(body)
    except ValueError as error:
        raise PairingRefused(f"The master's pairing answer is not JSON: {error}") from error
    if not isinstance(data, dict):
        raise PairingRefused("The master's pairing answer is not a JSON object")
    ensure_compatible(data.get("protocol_version"))
    return PairingResponse.model_validate(data)


def _error_detail(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    try:
        body = str(json.loads(body).get("detail", body))
    except (ValueError, AttributeError):
        pass
    return f": {body[:200]}" if body else ""
