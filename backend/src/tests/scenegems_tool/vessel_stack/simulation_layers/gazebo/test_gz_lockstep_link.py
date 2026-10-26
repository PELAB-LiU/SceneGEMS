"""gz lockstep link: the runner's side of the actuator protocol, against the actuator on a fake gz sim over a real TCP socket."""

import json
import math
import socket
import threading

import pytest

from scenegems_tool.vessel_stack.simulation_layers.gazebo import gz_lockstep_link
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_link import GzLockstepLink, GzLockstepLinkError, HullOdometry
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_transport_actuator import GzTransportActuator, InProcessWorldControl, serve_connection
from tests.scenegems_tool.vessel_stack.simulation_layers.gazebo.fake_gz import MESSAGES, THRUSTER, FakeTransport, FakeWorld


def odometry(yaw: float = 0.0, surge: float = 0.0, sway: float = 0.0, yaw_rate: float = 0.0) -> HullOdometry:
    return HullOdometry(1.0, 2.0, -0.1, 0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2), surge, sway, 0.0, 0.0, 0.0, yaw_rate)


class Server:
    """A listening socket on localhost; each accepted connection goes to the next handler."""

    def __init__(self, *handlers):
        self.socket = socket.create_server(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, args=(handlers,), daemon=True)
        self.thread.start()

    def _serve(self, handlers):
        for handler in handlers:
            connection, _ = self.socket.accept()
            handler(connection)
        self.socket.close()


def actuator_handler(world: FakeWorld):
    def handle(connection):
        transport = FakeTransport(world)
        serve_connection(GzTransportActuator(transport, MESSAGES, world_control=InProcessWorldControl(transport.Node(), MESSAGES), sleep=lambda _: None), connection)

    return handle


def replying(*replies):
    """A handler that answers every request line with the next reply."""

    def handle(connection):
        reader = connection.makefile("r", encoding="utf-8")
        for reply in replies:
            if not reader.readline():
                break
            connection.sendall((json.dumps(reply) + "\n").encode("utf-8"))
        connection.close()

    return handle


class TestHullOdometry:
    def test_heading_comes_from_the_quaternion(self):
        assert odometry(math.pi / 2).heading == pytest.approx(math.pi / 2)
        assert odometry(-2.5).heading == pytest.approx(-2.5)

    def test_speed_includes_sway(self):
        assert odometry(surge=3.0, sway=4.0).speed == 5.0

    def test_actor_state_and_observation(self):
        hull = odometry(0.3, surge=2.0, yaw_rate=0.1)
        state = hull.actor_state()
        assert (state.x, state.y, state.speed) == (1.0, 2.0, 2.0)
        assert state.heading == pytest.approx(0.3)
        observation = hull.observation()
        assert (observation.surge, observation.yaw_rate) == (2.0, 0.1)
        assert observation.heading == pytest.approx(0.3)


class TestLink:
    def test_start_step_and_close_through_the_actuator(self):
        world = FakeWorld()
        server = Server(actuator_handler(world))
        with GzLockstepLink("127.0.0.1", server.port) as link:
            link.connect(timeout_s=5.0)
            started = link.start({"vessel_0": THRUSTER}, step_ns=5_000_000, settle_iterations=40)
            assert started.sim_time_ns == 200_000_000
            assert started.odometry["vessel_0"].x == 0.0
            result = link.step(20, {"vessel_0": (100.0, 200.0)})
        server.thread.join(5.0)
        assert result.sim_time_ns == 300_000_000
        assert result.odometry["vessel_0"].x == world.x["vessel_0"]
        assert result.late == ()
        assert not server.thread.is_alive(), "close ends the actuator's connection"

    def test_connect_retries_until_the_actuator_answers_hello(self, monkeypatch):
        """A published Docker port accepts and drops connections before the actuator listens behind it."""
        monkeypatch.setattr(gz_lockstep_link.time, "sleep", lambda _: None)
        server = Server(lambda connection: connection.close(), actuator_handler(FakeWorld()))
        link = GzLockstepLink("127.0.0.1", server.port)
        link.connect(timeout_s=5.0)
        link.close()

    def test_another_protocol_version_is_refused(self):
        server = Server(replying({"op": "hello", "protocol": 99}))
        with pytest.raises(GzLockstepLinkError, match="speaks protocol 99"):
            GzLockstepLink("127.0.0.1", server.port).connect(timeout_s=5.0)

    def test_an_error_reply_raises(self):
        server = Server(replying({"op": "hello", "protocol": 1}, {"op": "error", "message": "no thrust for ['vessel_0']"}))
        link = GzLockstepLink("127.0.0.1", server.port)
        link.connect(timeout_s=5.0)
        with pytest.raises(GzLockstepLinkError, match="no thrust for"):
            link.step(20, {})
        link.close()

    def test_a_request_before_connecting_raises(self):
        with pytest.raises(GzLockstepLinkError, match="not connected"):
            GzLockstepLink("127.0.0.1", 1).step(20, {})
