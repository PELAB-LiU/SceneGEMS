"""The node daemon: pairing, the control connection to the master, and the job runtime.

Start-up order:
    1. pair on first start, or load the stored pairing (pairing/);
    2. build the NodeContext and remove instances a crashed predecessor left;
    3. connect: Hello, then the master's Welcome sets the heartbeat interval and lease timeout;
    4. serve lease messages until the connection drops, then reconnect with backoff.

Running jobs belong to the LeaseManager, not to a connection, so they keep running
while the daemon reconnects; the next Hello names their leases. A ticker thread renews
leases, sends heartbeats and streams reports whether or not a connection is up.

Conditions that no retry can fix stop the daemon with DaemonStopped: the master refused
the credential, speaks another protocol version, or is not the paired master.
"""

import logging
import ssl
import threading
import time
import urllib.error
from typing import Callable, Optional

from scenegems_tool.cluster.node.daemon.configuration.node_configuration import NodeConfiguration
from scenegems_tool.cluster.node.daemon.control.control_link import ControlLink, CredentialRejected, LinkClosed
from scenegems_tool.cluster.node.daemon.control.reconnect_backoff import ReconnectBackoff
from scenegems_tool.cluster.node.daemon.control.status_frames import StatusFrames, software_revision
from scenegems_tool.cluster.node.daemon.leases.lease_manager import LeaseManager
from scenegems_tool.cluster.node.daemon.leases.lease_worker import JobRunner
from scenegems_tool.cluster.node.daemon.leases.slot_table import SlotTable
from scenegems_tool.cluster.node.daemon.node_runtime import build_node_context, remove_leftover_instances
from scenegems_tool.cluster.node.daemon.pairing.ca_pinning import verified_context
from scenegems_tool.cluster.node.daemon.pairing.node_pairing import PairingCall, ensure_paired, pair_with_master
from scenegems_tool.cluster.node.daemon.pairing.pairing_state import StoredPairing
from scenegems_tool.cluster.node.daemon.resource_probe import ResourceProbe
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.protocol.codec import MalformedFrame
from scenegems_tool.cluster.protocol.messages import MasterMessage, ProtocolError, ProtocolErrorCode, Welcome
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame
from scenegems_tool.cluster.protocol.version import ProtocolVersionMismatch
from utils.file_system_utils import RUNTIME_ASSETS_FOLDER

_logger = logging.getLogger(__name__)

WELCOME_TIMEOUT_S = 30.0
RECEIVE_POLL_S = 0.5  # how often the connection thread looks at the stop event
TICK_S = 0.25
SHUTDOWN_TIMEOUT_S = 30.0  # time for running jobs to stop and remove their containers


class DaemonStopped(RuntimeError):
    """A condition no reconnect can fix; the message says what the operator must do."""


class _CurrentLink:
    """The sender the lease manager and the ticker use: whatever connection is up, or none."""

    def __init__(self) -> None:
        self.link: Optional[ControlLink] = None

    @property
    def connected(self) -> bool:
        link = self.link
        return link is not None and link.connected

    def send(self, frame: ProtocolFrame) -> bool:
        link = self.link
        return link is not None and link.send(frame)


class NodeDaemon:
    def __init__(
        self,
        configuration: NodeConfiguration,
        *,
        pair: PairingCall = pair_with_master,
        run: Optional[JobRunner] = None,
        probe: Optional[ResourceProbe] = None,
        fingerprints: Optional[Callable[[], dict]] = None,
        link_factory: Callable[..., ControlLink] = ControlLink,
        backoff: Optional[ReconnectBackoff] = None,
        node_context: Callable[[NodeConfiguration, object], NodeContext] = build_node_context,
        clean_leftovers: bool = True,
        welcome_timeout_s: float = WELCOME_TIMEOUT_S,
        shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
    ):
        self.configuration = configuration
        self._pair = pair
        self._run = run
        self._probe = probe or ResourceProbe(disk_path=RUNTIME_ASSETS_FOLDER)
        self._fingerprints = fingerprints
        self._link_factory = link_factory
        self._backoff = backoff or ReconnectBackoff()
        self._node_context = node_context
        self._clean_leftovers = clean_leftovers
        self._welcome_timeout_s = welcome_timeout_s
        self._shutdown_timeout_s = shutdown_timeout_s
        self._current = _CurrentLink()
        self._heartbeat_interval_s: Optional[float] = None
        self._next_heartbeat = 0.0
        self.pairing: Optional[StoredPairing] = None
        self.manager: Optional[LeaseManager] = None
        self.status: Optional[StatusFrames] = None
        self.connected = threading.Event()  # set while a connection is past its Welcome; for tests and health checks

    # Lifecycle

    def run(self, stop: threading.Event) -> None:
        """Run until stop is set (then release the running leases) or DaemonStopped is raised."""
        self.pairing = self._paired(stop)
        if self.pairing is None:
            return
        response = self.pairing.response
        node = self._node_context(self.configuration, response)
        if self._clean_leftovers:
            remove_leftover_instances(response.master_id, response.node_id)
        self.manager = LeaseManager(SlotTable(self.configuration.capabilities), node, self._current, run=self._run)
        self.status = StatusFrames(
            node_id=response.node_id,
            node_name=self.configuration.node_name,
            software_revision=software_revision(self.configuration.software_revision),
            machine=self.configuration.machine,
            capabilities=self.configuration.capabilities,
            labels=self.configuration.labels,
            resources=self._probe.read,
            fingerprints=self._fingerprints or _local_image_fingerprints,
            leases=self.manager,
        )
        ticker_stop = threading.Event()
        ticker = threading.Thread(target=self._tick_loop, args=(ticker_stop,), name="node-ticker", daemon=True)
        ticker.start()
        _logger.info("Node %s (%s) of master %s starts with slots %s", response.node_id, self.configuration.node_name, response.master_id, _slots_text(self.configuration))
        try:
            self._connection_loop(stop)
        finally:
            self.manager.shutdown("the node daemon stopped", self._shutdown_timeout_s)
            ticker_stop.set()
            ticker.join(timeout=5)
            link, self._current.link = self._current.link, None
            self.connected.clear()
            if link is not None:
                link.close()
            node.shutdown()
            if self._clean_leftovers:
                remove_leftover_instances(response.master_id, response.node_id)
            _logger.info("Node %s stopped", response.node_id)

    def _paired(self, stop: threading.Event) -> Optional[StoredPairing]:
        """The pairing, retried while the master is unreachable; refusals are final."""
        while not stop.is_set():
            try:
                return ensure_paired(self.configuration, pair=self._pair)
            except (urllib.error.URLError, OSError, TimeoutError) as error:
                if isinstance(error, urllib.error.HTTPError):
                    raise
                if isinstance(getattr(error, "reason", error), ssl.SSLCertVerificationError):
                    raise DaemonStopped(
                        f"The master's server certificate does not verify against its pinned CA: {error}. " "Check that SCENEGEMS_MASTER_URL uses an address the master's certificate lists."
                    ) from error
                delay = self._backoff.next_delay_s()
                _logger.warning("Cannot reach the master at %s to pair (%s); retrying in %.1f s", self.configuration.master_url, error, delay)
                stop.wait(delay)
        return None

    # Connection

    def _connection_loop(self, stop: threading.Event) -> None:
        response = self.pairing.response
        context = verified_context(response.ca_certificate_pem)
        while not stop.is_set():
            link = self._link_factory(self.configuration.master_url, response.node_credential, context)
            try:
                link.open()
                self._handshake(link)
                self._current.link = link
                self.connected.set()
                self._backoff.reset()
                _logger.info("Connected to master %s at %s", response.master_id, link.url)
                self._serve(link, stop)
            except CredentialRejected as error:
                raise DaemonStopped(str(error)) from error
            except ProtocolVersionMismatch as error:
                raise DaemonStopped(str(error)) from error
            except (LinkClosed, MalformedFrame) as error:
                _logger.warning("Control connection lost: %s", error)
            finally:
                if not stop.is_set():
                    self.connected.clear()
                    self._current.link = None
                    link.close()
            if stop.is_set():
                break  # the link stays open, so the shutdown can release the leases
            delay = self._backoff.next_delay_s()
            _logger.info("Reconnecting in %.1f s; %d leases keep running", delay, len(self.manager.running_lease_ids()))
            stop.wait(delay)

    def _handshake(self, link: ControlLink) -> None:
        if not link.send(self.status.hello()):
            raise LinkClosed("The connection closed before Hello was sent")
        deadline = time.monotonic() + self._welcome_timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LinkClosed(f"No Welcome from the master within {self._welcome_timeout_s:g} s")
            message = link.receive(timeout_s=remaining)
            if isinstance(message, Welcome):
                self._welcome(message)
                return
            if isinstance(message, ProtocolError):
                self._protocol_error(message)
                raise LinkClosed(f"The master refused the Hello: {message.code.value}: {message.message}")
            if message is not None:
                _logger.warning("Ignoring %s before the master's Welcome", message.type)

    def _welcome(self, welcome: Welcome) -> None:
        paired_master = self.pairing.response.master_id
        if welcome.master_id != paired_master:
            raise DaemonStopped(f"The master at {self.configuration.master_url} is {welcome.master_id!r}, but this node is paired with {paired_master!r}")
        self.manager.set_lease_timeout(welcome.lease_timeout_s)
        self._heartbeat_interval_s = welcome.heartbeat_interval_s
        self._next_heartbeat = time.monotonic() + welcome.heartbeat_interval_s

    def _serve(self, link: ControlLink, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                message = link.receive(timeout_s=RECEIVE_POLL_S)
            except MalformedFrame as error:
                _logger.warning("Ignoring a malformed frame from the master: %s", error)
                continue
            if message is not None:
                self._dispatch(message)

    def _dispatch(self, message: MasterMessage) -> None:
        if self.manager.handle(message):
            return
        if isinstance(message, ProtocolError):
            self._protocol_error(message)
            _logger.warning("Protocol error from the master: %s: %s", message.code.value, message.message)
        elif isinstance(message, Welcome):
            self._welcome(message)

    def _protocol_error(self, error: ProtocolError) -> None:
        if error.code == ProtocolErrorCode.UNAUTHORIZED:
            raise DaemonStopped(f"The master refused this node: {error.message}. Remove the node's state volume and pair again with a new token.")
        if error.code == ProtocolErrorCode.VERSION_MISMATCH:
            raise DaemonStopped(f"The master speaks another protocol version: {error.message}")

    # Ticker

    def _tick_loop(self, stop: threading.Event) -> None:
        while not stop.wait(TICK_S):
            try:
                self.manager.tick()
                self._heartbeat()
            except Exception:
                _logger.exception("Node ticker failed; continuing")

    def _heartbeat(self) -> None:
        if self._heartbeat_interval_s is None or not self._current.connected:
            return
        now = time.monotonic()
        if now >= self._next_heartbeat:
            self._next_heartbeat = now + self._heartbeat_interval_s
            self._current.send(self.status.heartbeat())


def _local_image_fingerprints() -> dict:
    from scenegems_tool.cluster.fingerprints.labels import read_image_fingerprints

    return read_image_fingerprints()


def _slots_text(configuration: NodeConfiguration) -> str:
    return ", ".join(f"{job_type.value}:{slots}" for job_type, slots in sorted(configuration.capabilities.items(), key=lambda item: item[0].value))
