"""The routes nodes use, served over HTTPS: CA certificate, pairing and the control WebSocket.

Only the CA certificate is served without a credential, since a new node needs it to trust
anything else; pairing needs a one-time token and the control socket the node credential.

    GET  CA_CERTIFICATE_PATH   the CA certificate as PEM: a new node checks its SHA-256
                               against the pinned value before trusting it
    POST PAIRING_PATH          PairingRequest to PairingResponse; 403 for a rejected token
    WS   NODE_CONTROL_PATH     the control link (control_link/node_control_socket.py)
"""

import json
import logging
from typing import Optional, Union

import anyio
from fastapi import APIRouter, Request, Response, WebSocket
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from scenegems_tool.cluster.master.control_link.node_control_socket import serve_node_control
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.protocol.pairing import PairingRequest
from scenegems_tool.cluster.protocol.routes import CA_CERTIFICATE_PATH, NODE_CONTROL_PATH, PAIRING_PATH
from scenegems_tool.cluster.protocol.version import ProtocolVersionMismatch, ensure_compatible
from scenegems_tool.cluster.security.credentials.node_credentials import authenticate_node
from scenegems_tool.cluster.security.master_security import MasterSecurity
from scenegems_tool.cluster.security.pairing import PairingTokenRejected, pair_node

logger = logging.getLogger(__name__)

PEM_MEDIA_TYPE = "application/x-pem-file"
MAX_PAIRING_REQUEST_BYTES = 64 * 1024


def node_router(plane: ControlPlane, security: MasterSecurity) -> APIRouter:
    router = APIRouter()
    ca_certificate_pem = security.ca_certificate_pem  # read once: the CA never changes while the master runs

    async def authenticate(credential: str) -> Optional[str]:
        if not credential:
            return None
        # scrypt takes tens of milliseconds; keep it off the event loop
        return await anyio.to_thread.run_sync(authenticate_node, security.store, credential)

    @router.get(CA_CERTIFICATE_PATH)
    async def ca_certificate() -> Response:
        return Response(content=ca_certificate_pem, media_type=PEM_MEDIA_TYPE)

    @router.post(PAIRING_PATH)
    async def pairing(request: Request) -> Response:
        pairing_request = _pairing_request(await request.body())
        if isinstance(pairing_request, JSONResponse):
            return pairing_request
        try:
            response = await anyio.to_thread.run_sync(pair_node, security, pairing_request)
        except PairingTokenRejected:
            logger.warning("Pairing refused for %r from %s: token rejected", pairing_request.node_name, request.client.host if request.client else "?")
            return JSONResponse({"detail": "pairing token rejected"}, status_code=403)
        logger.info("Paired node %s (%s)", response.node_id, pairing_request.node_name)
        return Response(content=response.model_dump_json(), media_type="application/json")

    @router.websocket(NODE_CONTROL_PATH)
    async def node_control(websocket: WebSocket) -> None:
        await serve_node_control(websocket, plane, authenticate)

    return router


def _pairing_request(body: bytes) -> Union[PairingRequest, JSONResponse]:
    """The decoded request, or the error answer: 413 too large, 400 another protocol version, 422 invalid."""
    if len(body) > MAX_PAIRING_REQUEST_BYTES:
        return JSONResponse({"detail": "pairing request too large"}, status_code=413)
    try:
        data = json.loads(body)
        if isinstance(data, dict) and "protocol_version" in data:
            ensure_compatible(data["protocol_version"])
        return PairingRequest.model_validate(data)
    except ProtocolVersionMismatch as error:
        return JSONResponse({"detail": str(error)}, status_code=400)
    except (ValueError, ValidationError) as error:
        return JSONResponse({"detail": f"invalid pairing request: {error}"}, status_code=422)
