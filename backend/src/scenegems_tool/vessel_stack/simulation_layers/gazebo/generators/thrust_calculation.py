"""Twin fixed thrusters of the generated vessel model, sized from the vessel's max speed.

Two propellers at the stern steer by thrust difference. Their full thrust together balances
the surge damping at the design speed (control margin times max speed), so an open-loop run
at full thrust settles at that speed. The gz-sim Thruster system applies the commanded force
directly; the thrust coefficient only sets how fast the propeller joint spins for it.
"""

import math
from dataclasses import dataclass

from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import RHO_WATER, damping_force


@dataclass(frozen=True)
class ThrusterSizing:
    max_thrust: float  # N per thruster, forward and reverse
    thruster_x: float  # m, ahead of the hull origin (negative: aft)
    thruster_y: float  # m, port thruster; starboard is mirrored
    thrust_coefficient: float  # Gazebo C_T for thrust = C_T * rho * omega^2 * D^4, omega in rad/s
    max_propeller_speed: float  # rad/s at max thrust, for reference


def size_thrusters(
    *,
    length: float,
    breadth: float,
    propeller_diameter: float,
    design_speed: float,
    xU: float,
    xUabsU: float,
    thruster_beam_ratio: float,
    thruster_aft_ratio: float,
    propeller_kt: float,
) -> ThrusterSizing:
    max_thrust = damping_force(xU, xUabsU, design_speed) / 2.0
    # K_T is defined with revolutions per second; Gazebo uses rad/s.
    thrust_coefficient = propeller_kt / (2.0 * math.pi) ** 2
    max_propeller_speed = math.sqrt(max_thrust / (thrust_coefficient * RHO_WATER * propeller_diameter**4))
    return ThrusterSizing(
        max_thrust=max_thrust,
        thruster_x=-(length / 2.0) * thruster_aft_ratio,
        thruster_y=(breadth / 2.0) * thruster_beam_ratio,
        thrust_coefficient=thrust_coefficient,
        max_propeller_speed=max_propeller_speed,
    )


def ardupilot_thrust_multiplier(max_thrust: float) -> float:
    """ArduPilotPlugin COMMAND multiplier: with offset -0.5, PWM 1000 to 2000 maps to -max_thrust to +max_thrust."""
    return 2.0 * max_thrust
