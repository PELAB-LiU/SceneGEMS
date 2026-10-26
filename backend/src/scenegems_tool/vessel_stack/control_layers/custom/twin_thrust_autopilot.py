"""Heading and speed autopilot of the custom control layer for a twin differential-thrust hull.

Two loops share the two thrusters:

- surge: the common thrust Tp + Ts. The speed reference moves toward the commanded speed at
  the vessel's max acceleration, as the kinematic layer does. Feedforward is the hull's surge
  damping at the reference and its inertia times the reference's acceleration, so the hull
  follows the reference without integral action. A PI term removes what the model misses.
- yaw: the differential thrust Ts - Tp, so the moment y (Ts - Tp). The heading error sets a turn
  rate demand within the vessel's max turn rate. The demand is linear near the heading and a
  square root farther out, so the hull can stop turning at the commanded heading with half its
  yaw deceleration. A rate loop turns the demand into a moment: yaw damping and inertia
  feedforward plus PI.

The gains come from the vessel model (AutopilotGains.from_dynamics). Each PI loop is placed as a
critically damped second-order loop on the hull's first-order surge or yaw dynamics, linearized
at half the max speed and at the max turn rate. Its natural frequency is BANDWIDTH times the
hull's own rate, c / m, but at most DISCRETE_LIMIT over the control step. The heading loop is
HEADING_SEPARATION times slower than the rate loop.

Thrust limits: each thruster gives at most max_thrust either way. Yaw has priority: the
differential is limited first and the common thrust gets what is left. An integrator holds
while its loop is saturated in the direction of its error (conditional integration), which is
the anti-windup.
"""

import math
from dataclasses import dataclass
from typing import Optional

from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.control_layers.custom.hull_surge_yaw_model import damping
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import VesselDynamics
from utils.math_utils import heading_diff

BANDWIDTH = 4.0  # closed-loop natural frequency of the surge and turn rate loops, times the hull's own c / m
DISCRETE_LIMIT = 0.3  # and at most this over the control step, so the sampled loop stays close to the continuous design
HEADING_SEPARATION = 2.0  # the heading loop is this many times slower than the turn rate loop
YAW_DECELERATION_SHARE = 0.5  # share of the yaw deceleration of full differential thrust the heading approach plans with
SURGE_DESIGN_SPEED_SHARE = 0.5  # the surge loop is linearized at this share of the max speed


@dataclass(frozen=True)
class AutopilotGains:
    max_thrust: float  # N per thruster, both ways
    thruster_arm: float  # m, lateral offset of each thruster
    surge_mass: float  # kg, rigid body and added mass
    surge_linear: float  # |xU|
    surge_quadratic: float  # |xUabsU|
    yaw_inertia: float  # kg m^2, rigid body and added inertia
    yaw_linear: float  # |nR|
    yaw_quadratic: float  # |nRabsR|
    speed_p: float  # N per m/s
    speed_i: float  # N per m
    rate_p: float  # N m per rad/s
    rate_i: float  # N m per rad
    heading_p: float  # rad/s per rad
    max_turn_rate: float  # rad/s
    max_acceleration: float  # m/s^2
    max_speed: float  # m/s

    @property
    def max_yaw_moment(self) -> float:
        return 2.0 * self.max_thrust * self.thruster_arm

    @property
    def heading_deceleration(self) -> float:
        """rad/s^2 the heading approach plans with."""
        return YAW_DECELERATION_SHARE * self.max_yaw_moment / self.yaw_inertia

    @classmethod
    def from_dynamics(cls, dynamics: VesselDynamics, vessel: ConcreteVessel, control_dt: float) -> "AutopilotGains":
        surge_mass = dynamics.total_mass + abs(dynamics.xDotU)
        design_speed = SURGE_DESIGN_SPEED_SHARE * vessel.max_speed
        surge_slope = abs(dynamics.xU) + 2.0 * abs(dynamics.xUabsU) * design_speed
        yaw_inertia = dynamics.hull_izz + abs(dynamics.nDotR)
        yaw_slope = abs(dynamics.nR) + 2.0 * abs(dynamics.nRabsR) * vessel.max_angular_speed
        speed_p, speed_i, _ = _critically_damped_pi(surge_mass, surge_slope, control_dt)
        rate_p, rate_i, rate_frequency = _critically_damped_pi(yaw_inertia, yaw_slope, control_dt)
        return cls(
            max_thrust=dynamics.max_thrust,
            thruster_arm=dynamics.thruster_y,
            surge_mass=surge_mass,
            surge_linear=abs(dynamics.xU),
            surge_quadratic=abs(dynamics.xUabsU),
            yaw_inertia=yaw_inertia,
            yaw_linear=abs(dynamics.nR),
            yaw_quadratic=abs(dynamics.nRabsR),
            speed_p=speed_p,
            speed_i=speed_i,
            rate_p=rate_p,
            rate_i=rate_i,
            heading_p=rate_frequency / HEADING_SEPARATION,
            max_turn_rate=vessel.max_angular_speed,
            max_acceleration=vessel.max_acceleration,
            max_speed=vessel.max_speed,
        )


def _critically_damped_pi(mass: float, slope: float, control_dt: float):
    """P and I placing m s^2 + (c + P) s + I at a double pole, and that pole's frequency."""
    frequency = min(BANDWIDTH * slope / mass, DISCRETE_LIMIT / control_dt)
    return max(2.0 * frequency * mass - slope, 0.0), mass * frequency**2, frequency


@dataclass(frozen=True)
class HullObservation:
    heading: float  # rad, counterclockwise from east
    surge: float  # m/s, body x
    yaw_rate: float  # rad/s, counterclockwise


@dataclass(frozen=True)
class ThrustCommand:
    port: float  # N
    starboard: float  # N
    yaw_saturated: bool
    surge_saturated: bool


class TwinThrustAutopilot:
    def __init__(self, gains: AutopilotGains):
        self.gains = gains
        self.reset()

    def reset(self, speed: Optional[float] = None) -> None:
        """Clear the integrators. The speed reference starts at `speed`, or at the first observed surge speed when None."""
        self._speed_reference: Optional[float] = speed
        self._speed_integral = 0.0  # m
        self._rate_integral = 0.0  # rad
        self._previous_rate_demand: Optional[float] = None

    def turn_rate_demand(self, heading_error: float) -> float:
        """Linear near the heading, sqrt(2 a |e|) farther out (a the planned deceleration), within the max turn rate."""
        g = self.gains
        gain, deceleration = g.heading_p, g.heading_deceleration
        magnitude = abs(heading_error)
        linear_limit = deceleration / gain**2
        if magnitude <= linear_limit:
            demand = gain * magnitude
        else:
            demand = math.sqrt(2.0 * deceleration * (magnitude - linear_limit / 2.0))
        return math.copysign(min(demand, g.max_turn_rate), heading_error)

    def command(self, desired_heading: float, desired_speed: float, observation: HullObservation, dt: float) -> ThrustCommand:
        g = self.gains
        target_speed = min(max(desired_speed, 0.0), g.max_speed)
        if self._speed_reference is None:
            self._speed_reference = observation.surge
        step = g.max_acceleration * dt
        previous_reference = self._speed_reference
        self._speed_reference = min(max(target_speed, previous_reference - step), previous_reference + step)
        speed_reference = self._speed_reference
        acceleration = (speed_reference - previous_reference) / dt

        rate_demand = self.turn_rate_demand(heading_diff(desired_heading, observation.heading))
        rate_change = 0.0 if self._previous_rate_demand is None else (rate_demand - self._previous_rate_demand) / dt
        self._previous_rate_demand = rate_demand

        rate_error = rate_demand - observation.yaw_rate
        moment = damping(g.yaw_linear, g.yaw_quadratic, rate_demand) + g.yaw_inertia * rate_change + g.rate_p * rate_error + g.rate_i * self._rate_integral
        speed_error = speed_reference - observation.surge
        force = damping(g.surge_linear, g.surge_quadratic, speed_reference) + g.surge_mass * acceleration + g.speed_p * speed_error + g.speed_i * self._speed_integral

        # Allocation: yaw first, the common thrust within what is left.
        differential = moment / g.thruster_arm  # starboard minus port
        differential_limit = 2.0 * g.max_thrust
        yaw_saturated = abs(differential) > differential_limit
        differential = min(max(differential, -differential_limit), differential_limit)
        common_limit = differential_limit - abs(differential)
        surge_saturated = abs(force) > common_limit
        common = min(max(force, -common_limit), common_limit)

        # Conditional integration: hold an integrator that would push further into its limit.
        if not (yaw_saturated and math.copysign(1.0, rate_error) == math.copysign(1.0, moment)):
            self._rate_integral += rate_error * dt
        if not (surge_saturated and math.copysign(1.0, speed_error) == math.copysign(1.0, force)):
            self._speed_integral += speed_error * dt
        return ThrustCommand(
            port=(common - differential) / 2.0,
            starboard=(common + differential) / 2.0,
            yaw_saturated=yaw_saturated,
            surge_saturated=surge_saturated,
        )
