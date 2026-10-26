"""ArduPilot Rover parameters of one vessel: limits from the vessel, steering and speed control from the plant it drives.

The navigation limits (turn rate, speed, acceleration) are the vessel's. The steering and speed
controllers are derived from the yaw and surge dynamics of the simulation layer's plant, so
that the feedforward alone gives the commanded turn rate and speed and the PI terms only remove
what the linear feedforward misses:

- gazebo: the generated twin-thrust hull (simulation_layers/gazebo/generators/vessel_dynamics.py).
  ArduPilot skid steers it: ThrottleLeft drives the port thruster, ThrottleRight the starboard
  one, so steering is differential thrust and throttle the common thrust.
- ardupilot_sim: SITL's motorboat (libraries/SITL/SIM_Sailboat.cpp at the pinned commit): one
  rudder on servo 1 and one throttle on servo 3, a 1.8 m turning circle at 35 degrees of rudder,
  50 N of thrust per unit throttle against 0.5 v^2 of hull drag on 2 kg (10 m/s at full throttle)
  and no yaw inertia. Its size does not follow the vessel; the parameters cap it at the vessel's limits.
  Skid outputs on this frame made SITL read the steering as throttle, so the boat crept while
  ArduPilot held its heading at rest (WP3 finding).

A plant of the gazebo layer is the hull the vessel model generator would write for this vessel
and environment; a vessel with its own SDF (VesselConfig.gazebo_vessel_model) gets the gains of
the generated hull.

Rover GUIDED clamps a heading and speed target to WP_SPEED, so a vessel driven by GUIDED targets
gets the vessel's max speed there. Before, WP_SPEED was the trajectory's cruise speed and the
replay follower could not catch up after the start (it trailed by about 11 m, WP3 finding).
ArduAgent missions keep the cruise speed, since WP_SPEED is their mission speed.
"""

import math
from dataclasses import dataclass
from typing import Mapping, Optional

import numpy as np

from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import WaveConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import VesselDynamics, derive_vessel_dynamics

GRAVITY = 9.81
SERVO_GROUND_STEERING = 26
SERVO_THROTTLE = 70
SERVO_THROTTLE_LEFT = 73
SERVO_THROTTLE_RIGHT = 74
CRUISE_THROTTLE_RANGE = (5.0, 100.0)  # percent; Rover ignores its speed nudge outside this range

# SITL motorboat (SIM_Sailboat.cpp with a motor, pinned ArduPilot commit).
SITL_TURNING_CIRCLE_M = 1.8
SITL_RUDDER_ANGLE_MAX_DEG = 35.0
SITL_THRUST_PER_THROTTLE_N = 50.0
SITL_HULL_DRAG_COEFFICIENT = 0.5  # N per (m/s)^2
SITL_BOAT_MASS_KG = 2.0
SITL_TOP_SPEED = math.sqrt(SITL_THRUST_PER_THROTTLE_N / SITL_HULL_DRAG_COEFFICIENT)
MOTOR_SPEED_SCALE_BASE = 1.0  # MOT_SPD_SCA_BASE: above this speed Rover scales rudder steering by base / speed

# Closed-loop shaping, the same for every plant.
RATE_LOOP_SPEEDUP = 2.0  # the turn rate loop settles this many times faster than the open-loop hull
HEADING_LOOP_SEPARATION = 2.0  # the heading loop is this many times slower than the turn rate loop
SPEED_LOOP_SPEEDUP = 2.0
YAW_ACCEL_SHARE = 1.0  # share of the hull's yaw acceleration at full differential thrust the controller may ask for


@dataclass(frozen=True)
class ControlParameters:
    """What the plant decides: outputs, feedforwards, PI gains and the speeds of the plant."""

    servo1_function: int
    servo3_function: int
    skid_steering: bool
    turn_rate_ff: float  # steering per rad/s of turn rate at the vessel's max turn rate
    turn_rate_p: float
    turn_rate_i: float
    heading_p: float  # rad/s of turn rate per rad of heading error
    turn_accel_max_deg: float  # deg/s^2 of turn rate change; 0 leaves Rover's default
    cruise_throttle_percent: float
    speed_p: float
    speed_i: float
    top_speed: float  # m/s at full throttle

    def as_params(self) -> dict:
        return {
            "SERVO1_FUNCTION": self.servo1_function,
            "SERVO3_FUNCTION": self.servo3_function,
            "SKID_STEER_OUT": 1 if self.skid_steering else 0,
            "ATC_STR_RAT_FF": self.turn_rate_ff,
            "ATC_STR_RAT_P": self.turn_rate_p,
            "ATC_STR_RAT_I": self.turn_rate_i,
            "ATC_STR_RAT_D": 0.0,
            "ATC_STR_ANG_P": self.heading_p,
            "ATC_SPEED_P": self.speed_p,
            "ATC_SPEED_I": self.speed_i,
            "ATC_SPEED_D": 0.0,
            "CRUISE_THROTTLE": self.cruise_throttle_percent,
        }


def _cruise_throttle(throttle_fraction: float) -> float:
    return float(np.clip(100.0 * throttle_fraction, *CRUISE_THROTTLE_RANGE))


def gazebo_control_parameters(dynamics: VesselDynamics, max_turn_rate: float, cruise_speed: float) -> ControlParameters:
    """Gains of the generated twin-thrust hull.

    Yaw: steering s gives a moment of 2 s T y (T the max thrust per thruster, y its lateral arm),
    which the hull's yaw damping |nR| r + |nRabsR| r^2 balances at a steady turn rate r. The
    feedforward is the steering of the vessel's max turn rate over that rate. Linearized there,
    the hull is first order with gain 2 T y / c and time constant (Izz - nDotR) / c, c the damping
    slope; the PI zero cancels that pole and the loop settles RATE_LOOP_SPEEDUP times faster.
    Surge: throttle t gives 2 t T against |xU| u + |xUabsU| u^2, the same way.
    """
    arm_moment = 2.0 * dynamics.max_thrust * dynamics.thruster_y
    yaw_damping = abs(dynamics.nR) * max_turn_rate + abs(dynamics.nRabsR) * max_turn_rate**2
    turn_rate_ff = yaw_damping / arm_moment / max_turn_rate
    yaw_slope = abs(dynamics.nR) + 2.0 * abs(dynamics.nRabsR) * max_turn_rate
    yaw_inertia = dynamics.hull_izz + abs(dynamics.nDotR)
    yaw_time_constant = yaw_inertia / yaw_slope
    yaw_gain = arm_moment / yaw_slope  # rad/s of steady turn rate per unit steering, at the max turn rate
    turn_rate_p = (RATE_LOOP_SPEEDUP - 1.0) / yaw_gain
    rate_loop_time_constant = yaw_time_constant / RATE_LOOP_SPEEDUP
    heading_p = 1.0 / (HEADING_LOOP_SEPARATION * rate_loop_time_constant)
    turn_accel_max = YAW_ACCEL_SHARE * arm_moment / yaw_inertia

    thrust = 2.0 * dynamics.max_thrust
    cruise = min(cruise_speed, dynamics.design_speed)
    surge_damping = abs(dynamics.xU) * cruise + abs(dynamics.xUabsU) * cruise**2
    surge_slope = abs(dynamics.xU) + 2.0 * abs(dynamics.xUabsU) * cruise
    surge_mass = dynamics.total_mass + abs(dynamics.xDotU)
    speed_p = (SPEED_LOOP_SPEEDUP - 1.0) * surge_slope / thrust
    speed_i = speed_p * surge_slope / surge_mass
    return ControlParameters(
        servo1_function=SERVO_THROTTLE_LEFT,
        servo3_function=SERVO_THROTTLE_RIGHT,
        skid_steering=True,
        turn_rate_ff=turn_rate_ff,
        turn_rate_p=turn_rate_p,
        turn_rate_i=turn_rate_p / yaw_time_constant,
        heading_p=heading_p,
        turn_accel_max_deg=math.degrees(turn_accel_max),
        cruise_throttle_percent=_cruise_throttle(surge_damping / thrust),
        speed_p=speed_p,
        speed_i=speed_i,
        top_speed=dynamics.design_speed,
    )


def sitl_rudder_steering(turn_rate: float, speed: float) -> float:
    """Steering that turns SITL's motorboat at turn_rate (rad/s) at speed (m/s), Rover's speed scaling included.

    SITL turns on a circle of SITL_TURNING_CIRCLE_M * sin(35 deg) / sin(s * 35 deg) at the boat's
    speed, and Rover scales steering by MOT_SPD_SCA_BASE / speed above that base speed.
    """
    rudder_max = math.radians(SITL_RUDDER_ANGLE_MAX_DEG)
    sine = turn_rate * SITL_TURNING_CIRCLE_M * math.sin(rudder_max) / (2.0 * speed)
    rudder = math.asin(min(1.0, sine)) / rudder_max
    return rudder * max(1.0, speed / MOTOR_SPEED_SCALE_BASE)


def sitl_motorboat_control_parameters(max_turn_rate: float, cruise_speed: float) -> ControlParameters:
    """Gains of SITL's motorboat: a rudder whose turn rate follows the steering at once (no yaw inertia),
    and a hull whose speed settles at 10 sqrt(throttle) m/s."""
    cruise = min(cruise_speed, SITL_TOP_SPEED)
    reference_speed = max(cruise, MOTOR_SPEED_SCALE_BASE)
    turn_rate_ff = sitl_rudder_steering(max_turn_rate, reference_speed) / max_turn_rate
    # No yaw inertia: the turn rate loop only trims the feedforward, and the heading loop is
    # limited by Rover's 50 Hz scheduler and the rate filter, not by the plant.
    cruise_throttle = SITL_HULL_DRAG_COEFFICIENT * cruise**2 / SITL_THRUST_PER_THROTTLE_N
    surge_slope = 2.0 * SITL_HULL_DRAG_COEFFICIENT * cruise
    speed_p = (SPEED_LOOP_SPEEDUP - 1.0) * surge_slope / SITL_THRUST_PER_THROTTLE_N
    return ControlParameters(
        servo1_function=SERVO_GROUND_STEERING,
        servo3_function=SERVO_THROTTLE,
        skid_steering=False,
        turn_rate_ff=turn_rate_ff,
        turn_rate_p=0.5 * turn_rate_ff,
        turn_rate_i=0.5 * turn_rate_ff,
        heading_p=2.0,
        turn_accel_max_deg=0.0,
        cruise_throttle_percent=_cruise_throttle(cruise_throttle),
        speed_p=speed_p,
        speed_i=speed_p * surge_slope / SITL_BOAT_MASS_KG,
        top_speed=SITL_TOP_SPEED,
    )


def control_parameters(
    vessel: ConcreteVessel, cruise_speed: float, simulation_layer: SimulationLayerId, wind_speed: float = 0.0, overrides: Optional[Mapping[str, float]] = None
) -> Optional[ControlParameters]:
    """The plant's gains, or None for a vessel that cannot turn or move (no control law to derive)."""
    if vessel.max_angular_speed <= 0 or vessel.max_speed <= 0:
        return None
    if simulation_layer == SimulationLayerId.GAZEBO:
        if overrides is None:
            from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics_overrides import load_vessel_dynamics_overrides

            overrides = load_vessel_dynamics_overrides().for_vessel(vessel)
        return gazebo_control_parameters(derive_vessel_dynamics(vessel, wind_speed, overrides), vessel.max_angular_speed, cruise_speed)
    if simulation_layer == SimulationLayerId.ARDUPILOT_SIM:
        return sitl_motorboat_control_parameters(vessel.max_angular_speed, cruise_speed)
    raise ValueError(f"ArduPilot does not drive the {simulation_layer.value} simulation layer")


def generate_ardu_params(
    vessel: ConcreteVessel,
    cruise_speed: float,
    wind: np.ndarray,
    wave: WaveConfig,
    simulation_layer: SimulationLayerId = SimulationLayerId.ARDUPILOT_SIM,
    *,
    guided_targets: bool = False,
    overrides: Optional[Mapping[str, float]] = None,
) -> dict:
    """ArduPilot Rover parameters of a vessel on a simulation layer.

    cruise_speed is the trajectory's max speed. guided_targets: the vessel is driven by GUIDED
    heading and speed targets (the lockstep MAVLink adapters), so WP_SPEED, which caps those
    targets, is the vessel's max speed; otherwise it is the cruise speed of an ArduAgent mission.
    overrides are the vessel dynamics overrides of a gazebo hull (the vessel_dynamics files' when None).
    """
    max_turn_rate = vessel.max_angular_speed
    controls = control_parameters(vessel, cruise_speed, simulation_layer, float(np.linalg.norm(wind)), overrides)
    top_speed = controls.top_speed if controls is not None else vessel.max_speed
    speed_limit = min(vessel.max_speed, top_speed)
    cruise = min(cruise_speed, speed_limit)

    # Rover limits the turn rate to TURN_MAX_G * g / speed as well. At least 1 g keeps that limit
    # above ATC_STR_RAT_MAX at every speed the vessel reaches, so only the vessel's turn rate applies.
    turning_radius = vessel.max_speed / max_turn_rate if max_turn_rate > 0 else vessel.length * 5
    turn_max_g = max(vessel.max_speed**2 / (turning_radius * GRAVITY), 1.0)

    # Waypoint capture geometry of ArduAgent missions. ConcreteVessel.waypoint_radius is length * 4.0;
    # clamped so tiny USVs still get a usable radius and very long vessels do not get an absurd one
    # relative to the thinned mission leg length. The overshoot lets the hull re-intercept a leg after
    # a tight corner instead of looping back to the missed point.
    wp_radius = float(np.clip(vessel.waypoint_radius, 3.0, 150.0))
    wp_overshoot = float(np.clip(turning_radius * 0.5, wp_radius, 200.0))

    params = {
        # Frame and mode
        "FRAME_CLASS": 2,  # 2 = boat
        "INITIAL_MODE": 10,  # 10 = Auto
        # Navigation. 0 disables pivot turns, so a skid-steered hull arcs through corners.
        "WP_PIVOT_ANGLE": 0,
        "WP_RADIUS": wp_radius,
        "WP_OVERSHOOT": wp_overshoot,
        "WP_SPEED": speed_limit if guided_targets else cruise,
        "CRUISE_SPEED": cruise,
        "SPEED_MAX": top_speed,
        # Longitudinal limits: the vessel's acceleration both ways, as the kinematic layer applies it.
        "ATC_ACCEL_MAX": vessel.max_acceleration,
        "ATC_DECEL_MAX": vessel.max_acceleration,
        # Lateral limits
        "TURN_MAX_G": turn_max_g,
        "ATC_STR_RAT_MAX": math.degrees(max_turn_rate),
        # Outputs: PWM 1500 is neutral for both thrusters and for the rudder.
        "SERVO1_MIN": 1000,
        "SERVO1_MAX": 2000,
        "SERVO1_TRIM": 1500,
        "SERVO3_MIN": 1000,
        "SERVO3_MAX": 2000,
        "SERVO3_TRIM": 1500,
        "SERVO_32_ENABLE": 0,
        "BATT_MONITOR": 4,
        # Failsafes and arming checks: off in simulation
        "ARMING_CHECK": 0,
        "ARMING_REQUIRE": 0,  # no arming required
        "FS_GCS_ENABLE": 0,
        "FS_THR_ENABLE": 0,
        "FS_CRASH_CHECK": 0,
        "FS_EKF_ACTION": 0,
        "BAT_FS": 0,
        "FS_ACTION": 0,
        "FS_TIMEOUT": 60,
    }
    if controls is not None:
        params.update(controls.as_params())
        if controls.turn_accel_max_deg > 0:
            params["ATC_STR_ACC_MAX"] = controls.turn_accel_max_deg
    else:
        skid = simulation_layer == SimulationLayerId.GAZEBO
        params.update(
            {
                "SERVO1_FUNCTION": SERVO_THROTTLE_LEFT if skid else SERVO_GROUND_STEERING,
                "SERVO3_FUNCTION": SERVO_THROTTLE_RIGHT if skid else SERVO_THROTTLE,
                "SKID_STEER_OUT": 1 if skid else 0,
            }
        )

    environment_params = {
        "SIM_WIND_SPD": np.linalg.norm(wind),  # wind speed in m/s
        "SIM_WIND_DIR": np.degrees(np.arctan2(wind[1], wind[0])),
        "SIM_WIND_TURB": 0,
        "SIM_WIND_DIR_Z": 0,
        "SIM_WAVE_ENABLE": 1 if wave.is_enabled else 0,
        "SIM_WAVE_AMP": wave.amplitude,  # m
        "SIM_WAVE_DIR": np.degrees(np.arctan2(wave.direction[1], wave.direction[0])),
        "SIM_WAVE_LENGTH": wave.length,
        "SIM_WAVE_SPEED": wave.speed,
    }
    return {**params, **environment_params}
