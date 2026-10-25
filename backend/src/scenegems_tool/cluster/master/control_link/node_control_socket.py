"""The node's control WebSocket on the master: authentication, the Hello handshake, the frame loop.

A connection goes through four steps:

    1. The node opens the socket with its credential as a bearer header (routes.py).
       A missing or wrong credential gets ProtocolError(unauthorized) and close 1008.
    2. The first frame must be Hello, within ControlTiming.hello_timeout_s, and must name
       the node the credential belongs to. Another protocol version gets
       ProtocolError(version_mismatch) and close 1002; anything else invalid gets
       ProtocolError(malformed_frame) and close 1002.
    3. The control plane registers the node, reconciles its leases and sends Welcome.
    4. Every later frame goes to the control plane. A malformed frame is answered with
       ProtocolError and the connection stays; a version change mid-connection closes it.
"""

import asyncio
import logging
from typing import Awaitable, Callable, Optional, Union

from starlette.websockets import WebSocket, WebSocketDisconnect

from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.registry.node_session import NodeSession
from scenegems_tool.cluster.protocol.codec import MalformedFrame, decode_node_message, encode
from scenegems_tool.cluster.protocol.messages import Hello, ProtocolError, ProtocolErrorCode
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame
from scenegems_tool.cluster.protocol.routes import AUTHORIZATION_HEADER, credential_from_authorization
from scenegems_tool.cluster.protocol.version import ProtocolVersionMismatch

logger = logging.getLogger(__name__)

CLOSE_POLICY_VIOLATION = 1008  # not authenticated, or the Hello names another node
CLOSE_PROTOCOL_ERROR = 1002  # another protocol version, or no valid Hello

Authenticate = Callable[[str], Awaitable[Optional[str]]]  # credential to node id, None when invalid


class WebSocketControlSocket:
    """A starlette WebSocket as the control plane's ControlSocket: one frame at a time, errors as False."""

    def __init__(self, websocket: WebSocket):
        self._websocket = websocket
        self._send_lock = asyncio.Lock()

    async def send(self, frame: ProtocolFrame) -> bool:
        try:
            async with self._send_lock:
                await self._websocket.send_text(encode(frame))
            return True
        except Exception:  # closed or broken; the receive loop sees the disconnect
            return False

    async def close(self, code: int, reason: str) -> None:
        try:
            await self._websocket.close(code=code, reason=reason)
        except Exception:
            pass

    async def receive(self) -> Union[str, bytes]:
        message = await self._websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        text = message.get("text")
        return text if text is not None else message.get("bytes") or b""

    async def refuse(self, code: ProtocolErrorCode, message: str, close_code: int) -> None:
        await self.send(ProtocolError(code=code, message=message))
        await self.close(close_code, code.value)


async def serve_node_control(websocket: WebSocket, plane: ControlPlane, authenticate: Authenticate) -> None:
    await websocket.accept()
    socket = WebSocketControlSocket(websocket)
    node_id = await authenticate(credential_from_authorization(websocket.headers.get(AUTHORIZATION_HEADER, "")))
    if node_id is None:
        await socket.refuse(ProtocolErrorCode.UNAUTHORIZED, "Missing or invalid node credential", CLOSE_POLICY_VIOLATION)
        return
    hello = await _receive_hello(socket, plane.timing.hello_timeout_s)
    if hello is None:
        return
    if hello.node_id != node_id:
        await socket.refuse(ProtocolErrorCode.UNAUTHORIZED, f"The Hello names node {hello.node_id!r}, the credential belongs to {node_id!r}", CLOSE_POLICY_VIOLATION)
        return

    session = await plane.open_session(hello, socket)
    try:
        await _serve_frames(socket, session, plane)
    except (WebSocketDisconnect, RuntimeError):  # RuntimeError: receive after the master closed the socket
        pass
    finally:
        await plane.close_session(session)


async def _serve_frames(socket: WebSocketControlSocket, session: NodeSession, plane: ControlPlane) -> None:
    """Hands every frame to the control plane until the socket closes or the node changes its protocol version."""
    while True:
        try:
            frame = decode_node_message(await socket.receive())
        except ProtocolVersionMismatch as error:
            await socket.refuse(ProtocolErrorCode.VERSION_MISMATCH, str(error), CLOSE_PROTOCOL_ERROR)
            return
        except MalformedFrame as error:
            await session.send(ProtocolError(code=ProtocolErrorCode.MALFORMED_FRAME, message=str(error)))
            continue
        try:
            await plane.handle_frame(session, frame)
        except Exception:  # a store outage, for example: the lease timeouts cover what this frame missed
            logger.exception("Handling a %s frame of node %s failed", frame.type, session.node_id)


async def _receive_hello(socket: WebSocketControlSocket, timeout_s: float) -> Optional[Hello]:
    """The node's Hello, or None after refusing the connection."""
    try:
        frame = decode_node_message(await asyncio.wait_for(socket.receive(), timeout_s))
    except asyncio.TimeoutError:
        await socket.refuse(ProtocolErrorCode.MALFORMED_FRAME, f"No Hello within {timeout_s:.0f} s", CLOSE_PROTOCOL_ERROR)
        return None
    except ProtocolVersionMismatch as error:
        await socket.refuse(ProtocolErrorCode.VERSION_MISMATCH, str(error), CLOSE_PROTOCOL_ERROR)
        return None
    except MalformedFrame as error:
        await socket.refuse(ProtocolErrorCode.MALFORMED_FRAME, str(error), CLOSE_PROTOCOL_ERROR)
        return None
    except (WebSocketDisconnect, RuntimeError):
        return None
    if not isinstance(frame, Hello):
        await socket.refuse(ProtocolErrorCode.MALFORMED_FRAME, f"The first frame must be hello, got {frame.type}", CLOSE_PROTOCOL_ERROR)
        return None
    return frame
