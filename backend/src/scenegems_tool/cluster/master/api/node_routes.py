"""The route nodes use, served over plain HTTP on the VPN: the control WebSocket.

    WS   NODE_CONTROL_PATH     the control link (control_link/node_control_socket.py)

There is no pairing and no credential: the master trusts every machine that can reach it.
"""

from fastapi import APIRouter, WebSocket

from scenegems_tool.cluster.master.control_link.node_control_socket import serve_node_control
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.protocol.routes import NODE_CONTROL_PATH


def node_router(plane: ControlPlane) -> APIRouter:
    router = APIRouter()

    @router.websocket(NODE_CONTROL_PATH)
    async def node_control(websocket: WebSocket) -> None:
        await serve_node_control(websocket, plane)

    return router
