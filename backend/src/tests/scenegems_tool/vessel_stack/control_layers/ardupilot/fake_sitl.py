"""An in-process stand-in for one SITL vessel behind a pymavlink connection, for tests without Docker.

FakeSitlConnection implements the part of a pymavlink connection that MavlinkLink uses. The
vessel it simulates obeys the last GUIDED heading and speed target at once and moves on a flat
local frame; every 40 ms of its own clock it streams GLOBAL_POSITION_INT, every second a
HEARTBEAT, and at boot the EKF-ready status text. Its clock advances only when data is read,
a burst of ticks per read cycle, like a free-running SITL seen from the other end of a socket.
FakeLink is a MavlinkLink whose connect() installs such a connection.
"""

import math
import socket
from collections import deque
from types import SimpleNamespace
from typing import Any, Deque, Dict, List, Optional, Tuple

from pymavlink import mavutil

from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import EKF_READY_TEXT, ROVER_GUIDED_MODE, ROVER_HOLD_MODE, MavlinkLink

TICK_MS = 40
HEARTBEAT_MS = 1000
BURST_TICKS = 25  # one second of SITL time per read cycle


class FakeMessage(SimpleNamespace):
    def get_type(self) -> str:
        return self._type

    def get_srcSystem(self) -> int:
        return self._system

    def get_srcComponent(self) -> int:
        return self._component


def message(message_type: str, system: int = 1, component: int = 1, **fields: Any) -> FakeMessage:
    return FakeMessage(_type=message_type, _system=system, _component=component, **fields)


class SentMessages:
    """Records what the link sends, by method name."""

    def __init__(self, owner: "FakeSitlConnection"):
        self._owner = owner
        self.calls: List[Tuple[str, tuple]] = []

    def __getattr__(self, name: str):
        def record(*args: Any) -> None:
            self.calls.append((name, args))
            self._owner.on_send(name, args)

        return record

    def named(self, name: str) -> List[tuple]:
        return [args for call, args in self.calls if call == name]


class FakeSitlConnection:
    target_system = 1
    target_component = 1

    def __init__(self, geofence: Geofence, start_xy: Tuple[float, float] = (0.0, 0.0), start_heading_ned: float = math.pi / 2, boot_ms: int = 10_000, ekf_after_ms: int = 2_000):
        self.geofence = geofence
        self.mav = SentMessages(self)
        self.x, self.y = start_xy
        self.heading_ned = start_heading_ned  # radians clockwise from north
        self.speed = 0.0
        self.time_ms = boot_ms
        self.mode = 0
        self.armed = False
        self.ekf_at_ms = boot_ms + ekf_after_ms
        self.ekf_reported = False
        self.closed = False
        self._queue: Deque[FakeMessage] = deque()
        self._fed = False
        self._next_heartbeat_ms = boot_ms
        sockets = socket.socketpair()
        self._keepalive = sockets
        sockets[1].send(b"x")  # always readable for select
        self.port = SimpleNamespace(fileno=sockets[0].fileno)

    # The pymavlink connection interface used by MavlinkLink

    def recv_match(self, blocking: bool = False, timeout: Optional[float] = None) -> Optional[FakeMessage]:
        if not self._queue and not self._fed:
            for _ in range(BURST_TICKS):
                self._tick()
            self._fed = True
        if self._queue:
            return self._queue.popleft()
        self._fed = False
        return None

    def close(self) -> None:
        self.closed = True
        for end in self._keepalive:
            end.close()

    # What the vessel does with the commands it receives

    def on_send(self, name: str, args: tuple) -> None:
        if name == "set_mode_send":
            self.mode = int(args[2])
        elif name == "command_long_send" and args[2] == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
            self.armed = bool(args[4])
        elif name == "set_position_target_local_ned_send":
            self.heading_ned = float(args[14])
            self.speed = float(args[8])

    def _tick(self) -> None:
        self.time_ms += TICK_MS
        dt = TICK_MS / 1000.0
        if self.mode == ROVER_GUIDED_MODE and self.armed:
            self.x += self.speed * math.sin(self.heading_ned) * dt
            self.y += self.speed * math.cos(self.heading_ned) * dt
        else:
            self.speed = 0.0
        if not self.ekf_reported and self.time_ms >= self.ekf_at_ms:
            self.ekf_reported = True
            self._queue.append(message("STATUSTEXT", text=EKF_READY_TEXT))
        if self.time_ms >= self._next_heartbeat_ms:
            self._next_heartbeat_ms = self.time_ms + HEARTBEAT_MS
            base_mode = mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED if self.armed else 0
            self._queue.append(message("HEARTBEAT", base_mode=base_mode, custom_mode=self.mode))
        latitude, longitude = self.geofence.to_lat_long((self.x, self.y))
        north, east = self.speed * math.cos(self.heading_ned), self.speed * math.sin(self.heading_ned)
        self._queue.append(
            message(
                "GLOBAL_POSITION_INT",
                time_boot_ms=self.time_ms,
                lat=int(round(latitude * 1e7)),
                lon=int(round(longitude * 1e7)),
                vx=int(round(north * 100)),
                vy=int(round(east * 100)),
                hdg=int(round((math.degrees(self.heading_ned) % 360.0) * 100)),
            )
        )


class FakeLink(MavlinkLink):
    """A MavlinkLink on a fake SITL: connect() installs the connection instead of opening a socket."""

    connections: List[FakeSitlConnection] = []
    start_positions: Dict[int, Tuple[float, float]] = {}  # local start position by vessel id, default the origin
    connection_class = FakeSitlConnection

    def connect(self, timeout_s: float = 300.0) -> None:
        connection = self.connection_class(self.reference_geofence, start_xy=self.start_positions.get(self.vessel_id, (0.0, 0.0)))
        FakeLink.connections.append(connection)
        self._connection = connection
        self._send_gcs_heartbeat()
        self._request_streams()


class StuckSitlConnection(FakeSitlConnection):
    """A vessel that ignores mode changes, so it never leaves HOLD."""

    def on_send(self, name: str, args: tuple) -> None:
        if name != "set_mode_send":
            super().on_send(name, args)
        elif int(args[2]) == ROVER_HOLD_MODE:
            self.mode = ROVER_HOLD_MODE


class StuckLink(FakeLink):
    connection_class = StuckSitlConnection


def attach(link: MavlinkLink, connection: FakeSitlConnection) -> FakeSitlConnection:
    """Install a fake connection on an existing link (without sending the connect handshake)."""
    link._connection = connection
    return connection


__all__ = ["FakeLink", "FakeSitlConnection", "StuckLink", "attach", "message"]
