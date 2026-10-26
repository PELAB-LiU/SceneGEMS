"""Horizontal-plane model of the generated twin-thrust hull: the plant the custom autopilot is designed on and tested against.

The coefficients are the VesselDynamics the Gazebo model generator writes into the SDF
(simulation_layers/gazebo/generators/vessel_dynamics.py), restricted to surge, sway and yaw:

    (m - xDotU) du/dt =  m v r + Tp + Ts - (|xU| u + |xUabsU| u|u|)
    (m - yDotV) dv/dt = -m u r          - (|yV| v + |yVabsV| v|v|)
    (Izz - nDotR) dr/dt = y (Ts - Tp)   - (|nR| r + |nRabsR| r|r|)

with body x forward, y to port and the yaw rate r counterclockwise from above, so the
starboard thruster turns the hull to port. The rigid-body Coriolis terms are kept (Gazebo's
physics has them) and the added-mass ones left out, as the SDF disables them. There is no
buoyancy, roll, pitch, wind or wave here: the model is for designing gains and for tests, not a
substitute for Gazebo.
"""

import math
from dataclasses import dataclass

from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import VesselDynamics


def damping(linear: float, quadratic: float, value: float) -> float:
    """Magnitude-signed damping force (or moment) |linear| v + |quadratic| v|v| of a velocity v."""
    return abs(linear) * value + abs(quadratic) * value * abs(value)


@dataclass(frozen=True)
class HullState:
    x: float  # m, local frame (east)
    y: float  # m, local frame (north)
    heading: float  # rad, counterclockwise from east
    surge: float  # m/s, body x
    sway: float  # m/s, body y (to port)
    yaw_rate: float  # rad/s, counterclockwise

    @property
    def speed(self) -> float:
        return math.hypot(self.surge, self.sway)


class HullSurgeYawModel:
    def __init__(self, dynamics: VesselDynamics):
        self.dynamics = dynamics
        self.mass = dynamics.total_mass
        self.surge_mass = self.mass + abs(dynamics.xDotU)
        self.sway_mass = self.mass + abs(dynamics.yDotV)
        self.yaw_inertia = dynamics.hull_izz + abs(dynamics.nDotR)

    def step(self, state: HullState, port_thrust: float, starboard_thrust: float, dt: float) -> HullState:
        """One semi-implicit Euler step: velocities first, then the pose from the new velocities."""
        d = self.dynamics
        limit = d.max_thrust
        port = min(max(port_thrust, -limit), limit)
        starboard = min(max(starboard_thrust, -limit), limit)
        u, v, r = state.surge, state.sway, state.yaw_rate
        u_dot = (self.mass * v * r + port + starboard - damping(d.xU, d.xUabsU, u)) / self.surge_mass
        v_dot = (-self.mass * u * r - damping(d.yV, d.yVabsV, v)) / self.sway_mass
        r_dot = (d.thruster_y * (starboard - port) - damping(d.nR, d.nRabsR, r)) / self.yaw_inertia
        u, v, r = u + u_dot * dt, v + v_dot * dt, r + r_dot * dt
        heading = state.heading + r * dt
        cos_heading, sin_heading = math.cos(heading), math.sin(heading)
        return HullState(
            x=state.x + (u * cos_heading - v * sin_heading) * dt,
            y=state.y + (u * sin_heading + v * cos_heading) * dt,
            heading=math.atan2(sin_heading, cos_heading),
            surge=u,
            sway=v,
            yaw_rate=r,
        )
