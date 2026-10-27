"""A scripted master for the node daemon tests: plain HTTP and the control WebSocket on one port.

It serves the master's routes from cluster/protocol/routes.py, trusting every node as the
real master does on the VPN: a node is named by its Hello. It runs uvicorn in a thread; the test
drives each node connection from its own thread through FakeNodeConnection:

    connection = master.wait_for_connection()
    hello = connection.expect(Hello)
    connection.send(LeaseOffer(...))
    accept = connection.expect(LeaseAccept)

By default the master answers Hello with Welcome and LeaseRenew with LeaseRenewed, the
behaviour the node relies on; both can be switched off or replaced.

With `artifacts` it also serves the real artifact routes (cluster/master/api/artifact_routes.py)
on that store; a job offered on a connection counts as leased to its node (`leased_jobs`).
"""

import asyncio
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Type, Union

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from scenegems_tool.cluster.master.api.artifact_routes import DEFAULT_MAX_ARTIFACT_BYTES, node_artifact_router
from scenegems_tool.cluster.protocol.codec import decode_node_message, encode
from scenegems_tool.cluster.protocol.messages import Heartbeat, Hello, JobStatus, LeaseOffer, LeaseRenew, LeaseRenewed, LogLines, Welcome
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame
from scenegems_tool.cluster.protocol.routes import NODE_CONTROL_PATH
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts

TIMEOUT_S = 10.0
# Frames a test usually does not wait for; expect() skips them unless asked for.
BACKGROUND_FRAMES = (Heartbeat, JobStatus, LogLines, LeaseRenew)

HelloReply = Callable[[Hello], Union[ProtocolFrame, str, None]]  # a frame, raw text, or None for no answer


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FakeNodeConnection:
    def __init__(self, loop: asyncio.AbstractEventLoop, leased_jobs: Optional[Dict[str, str]] = None):
        self.node_id = ""  # named by the Hello
        self._leased_jobs = leased_jobs if leased_jobs is not None else {}
        self._loop = loop
        self._outbox: asyncio.Queue = asyncio.Queue()
        self._inbox: "queue.Queue" = queue.Queue()
        self.history: List[ProtocolFrame] = []  # every frame received, in order
        self.closed = threading.Event()

    def send(self, frame: Union[ProtocolFrame, str]) -> None:
        if isinstance(frame, LeaseOffer):
            self._leased_jobs[frame.job.job_id] = self.node_id  # as the master's job store records the lease
        text = frame if isinstance(frame, str) else encode(frame)
        self._loop.call_soon_threadsafe(self._outbox.put_nowait, text)

    def close(self) -> None:
        """The master drops the connection."""
        self._loop.call_soon_threadsafe(self._outbox.put_nowait, None)

    def expect(self, kinds: Union[Type, Tuple[Type, ...]], timeout_s: float = TIMEOUT_S, skip: Sequence[Type] = BACKGROUND_FRAMES):
        """The next frame of the given type; frames of the skipped types are passed over, anything else fails."""
        kinds = kinds if isinstance(kinds, tuple) else (kinds,)
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"No {', '.join(kind.__name__ for kind in kinds)} from node {self.node_id} within {timeout_s} s")
            try:
                frame = self._inbox.get(timeout=remaining)
            except queue.Empty:
                continue
            if isinstance(frame, kinds):
                return frame
            if not isinstance(frame, tuple(skip)):
                raise AssertionError(f"Expected {', '.join(kind.__name__ for kind in kinds)}, got {frame!r}")

    def received(self, kind: Type) -> List[ProtocolFrame]:
        return [frame for frame in self.history if isinstance(frame, kind)]

    def wait_until(self, condition: Callable[[], bool], timeout_s: float = TIMEOUT_S) -> None:
        deadline = time.monotonic() + timeout_s
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError(f"Condition not met within {timeout_s} s")
            time.sleep(0.02)

    # The master's side, on the event loop

    def _received(self, frame: ProtocolFrame) -> None:
        if isinstance(frame, Hello):
            self.node_id = frame.node_id
        self.history.append(frame)
        self._inbox.put(frame)


@dataclass
class FakeMaster:
    master_id: str = "lab-master"
    host: str = "127.0.0.1"
    heartbeat_interval_s: float = 0.2
    lease_timeout_s: float = 3.0
    hello_reply: Optional[HelloReply] = None  # replaces the Welcome
    renew_leases: bool = True
    connections: "queue.Queue[FakeNodeConnection]" = field(default_factory=queue.Queue)  # handed out by wait_for_connection
    all_connections: List[FakeNodeConnection] = field(default_factory=list)  # every connection, in order
    port: int = 0
    broker_port: int = 0  # of a cluster broker next to the master, for the tests that run one
    artifacts: Optional[RecordedArtifacts] = None
    leased_jobs: Dict[str, str] = field(default_factory=dict)  # job id to the node it was offered to, for uploads
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES

    def __post_init__(self) -> None:
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def welcome(self) -> Welcome:
        return Welcome(master_id=self.master_id, heartbeat_interval_s=self.heartbeat_interval_s, lease_timeout_s=self.lease_timeout_s)

    def wait_for_connection(self, timeout_s: float = TIMEOUT_S) -> FakeNodeConnection:
        try:
            return self.connections.get(timeout=timeout_s)
        except queue.Empty:
            raise AssertionError(f"No node connected within {timeout_s} s") from None

    # Server

    def start(self, bind: str = "127.0.0.1") -> "FakeMaster":
        config = uvicorn.Config(
            self._app(),
            host=bind,
            port=self.port,
            ws="websockets-sansio",
            timeout_graceful_shutdown=2,
            ws_max_size=64 * 1024 * 1024,
            lifespan="off",
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="fake-master", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + TIMEOUT_S
        while not self._server.started:
            if time.monotonic() > deadline or not self._thread.is_alive():
                raise RuntimeError("The fake master did not start")
            time.sleep(0.02)
        self.port = self._server.servers[0].sockets[0].getsockname()[1]
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
            self._thread.join(timeout=TIMEOUT_S)

    def __enter__(self) -> "FakeMaster":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    def _app(self) -> FastAPI:
        app = FastAPI()
        master = self
        self._include_artifact_routes(app)

        @app.websocket(NODE_CONTROL_PATH)
        async def control(websocket: WebSocket) -> None:
            await websocket.accept()
            connection = FakeNodeConnection(asyncio.get_running_loop(), master.leased_jobs)
            master.all_connections.append(connection)
            master.connections.put(connection)
            sender = asyncio.create_task(master._send_loop(websocket, connection))
            try:
                while True:
                    frame = decode_node_message(await websocket.receive_text())
                    connection._received(frame)
                    master._auto_reply(connection, frame)
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                connection.closed.set()
                sender.cancel()

        return app

    def _include_artifact_routes(self, app: FastAPI) -> None:
        if self.artifacts is not None:
            app.include_router(node_artifact_router(self.artifacts, self.leased_jobs.get, self.max_artifact_bytes))

    async def _send_loop(self, websocket: WebSocket, connection: FakeNodeConnection) -> None:
        while True:
            text = await connection._outbox.get()
            if text is None:
                await websocket.close(code=1001)
                return
            await websocket.send_text(text)

    def _auto_reply(self, connection: FakeNodeConnection, frame: ProtocolFrame) -> None:
        if isinstance(frame, Hello):
            reply = self.hello_reply(frame) if self.hello_reply is not None else self.welcome()
            if reply is not None:
                connection.send(reply)
        elif isinstance(frame, LeaseRenew) and self.renew_leases:
            connection.send(LeaseRenewed(lease_id=frame.lease_id, expires_at=_utc_now() + timedelta(seconds=self.lease_timeout_s)))
