"""generate_ardu_params: ArduPilot Rover parameters from the vessel's limits, the plant's dynamics and the environment."""

import math

import numpy as np
import pytest

from scenegems_tool.vessel_stack.calibration.reference_scenarios import VESSEL_SCALES, scaled_vessel
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, WaveConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardu_param_generator import (
    SITL_BOAT_MASS_KG,
    SITL_HULL_DRAG_COEFFICIENT,
    SITL_RUDDER_ANGLE_MAX_DEG,
    SITL_THRUST_PER_THROTTLE_N,
    SITL_TOP_SPEED,
    SITL_TURNING_CIRCLE_M,
    control_parameters,
    gazebo_control_parameters,
    generate_ardu_params,
    sitl_motorboat_control_parameters,
    sitl_rudder_steering,
)
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import derive_vessel_dynamics
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel

CALM = EnvironmentConfig.calm()
GAZEBO = SimulationLayerId.GAZEBO
ARDUPILOT_SIM = SimulationLayerId.ARDUPILOT_SIM


def params_for(vessel, cruise_speed=8.0, wind=None, wave=None, layer=ARDUPILOT_SIM, guided_targets=False):
    return generate_ardu_params(vessel, cruise_speed, CALM.wind_vector if wind is None else wind, CALM.wave if wave is None else wave, layer, guided_targets=guided_targets, overrides={})


def sitl_turn_rate(steering: float, speed: float) -> float:
    """SITL's motorboat turn rate (rad/s), Sailboat::get_yaw_rate with Rover's steering speed scaling."""
    rudder = steering / max(1.0, speed)
    turn_circle = SITL_TURNING_CIRCLE_M * math.sin(math.radians(SITL_RUDDER_ANGLE_MAX_DEG)) / math.sin(math.radians(rudder * SITL_RUDDER_ANGLE_MAX_DEG))
    return speed / (turn_circle / 2.0)


class TestSpeeds:
    def test_arduagent_missions_cruise_at_the_trajectory_speed(self):
        params = params_for(make_vessel(0, True, max_speed=9.0), cruise_speed=8.0)
        assert params["WP_SPEED"] == params["CRUISE_SPEED"] == 8.0

    def test_guided_targets_are_capped_at_the_vessels_max_speed_not_the_cruise_speed(self):
        """Rover clamps GUIDED speed targets to WP_SPEED; the cruise speed there made the replay follower trail (WP3)."""
        params = params_for(make_vessel(0, True, max_speed=9.0), cruise_speed=8.0, guided_targets=True)
        assert params["WP_SPEED"] == 9.0
        assert params["CRUISE_SPEED"] == 8.0

    def test_speeds_are_capped_at_what_the_plant_reaches(self):
        fast = make_vessel(0, True, max_speed=20.0)
        params = params_for(fast, cruise_speed=12.0, guided_targets=True)
        assert params["SPEED_MAX"] == pytest.approx(SITL_TOP_SPEED)
        assert params["WP_SPEED"] == params["CRUISE_SPEED"] == pytest.approx(SITL_TOP_SPEED)
        gazebo = params_for(fast, cruise_speed=12.0, layer=GAZEBO, guided_targets=True)
        assert gazebo["SPEED_MAX"] == pytest.approx(1.2 * 20.0), "full thrust settles at the control margin times the max speed"
        assert gazebo["WP_SPEED"] == 20.0

    def test_acceleration_limits_follow_the_vessel_both_ways(self):
        params = params_for(make_vessel(0, True, max_acceleration=0.4))
        assert params["ATC_ACCEL_MAX"] == params["ATC_DECEL_MAX"] == 0.4


class TestTurning:
    def test_turn_rate_is_the_max_angular_speed_in_degrees(self):
        for layer in (ARDUPILOT_SIM, GAZEBO):
            assert params_for(make_vessel(0, True, max_angular_speed=0.05), layer=layer)["ATC_STR_RAT_MAX"] == pytest.approx(math.degrees(0.05))

    def test_rollover_protection_is_bypassed_with_at_least_one_g(self):
        assert params_for(make_vessel(0, True))["TURN_MAX_G"] >= 1.0
        # v^2 / (R g) with R = v / omega: a fast turner exceeds 1 g
        fast = make_vessel(0, True, max_speed=30.0, max_angular_speed=3.0)
        assert params_for(fast)["TURN_MAX_G"] == pytest.approx(30.0 * 3.0 / 9.81)

    def test_a_vessel_that_cannot_turn_gets_no_control_law(self):
        vessel = make_vessel(0, True, max_angular_speed=0.0)
        assert control_parameters(vessel, 8.0, GAZEBO, overrides={}) is None
        for layer in (ARDUPILOT_SIM, GAZEBO):
            params = params_for(vessel, layer=layer)
            assert params["TURN_MAX_G"] >= 1.0
            assert params["ATC_STR_RAT_MAX"] == 0.0
            assert "ATC_STR_RAT_FF" not in params
        assert params_for(vessel, layer=GAZEBO)["SERVO1_FUNCTION"] == 73
        assert params_for(vessel)["SERVO1_FUNCTION"] == 26


class TestOutputs:
    def test_gazebo_skid_steers_the_two_thrusters(self):
        params = params_for(make_vessel(0, True), layer=GAZEBO)
        assert (params["SERVO1_FUNCTION"], params["SERVO3_FUNCTION"], params["SKID_STEER_OUT"]) == (73, 74, 1)

    def test_ardupilot_sim_drives_a_rudder_and_a_throttle(self):
        """Skid outputs on SITL's motorboat frame read as rudder and throttle, so the boat crept at rest (WP3)."""
        params = params_for(make_vessel(0, True))
        assert (params["SERVO1_FUNCTION"], params["SERVO3_FUNCTION"], params["SKID_STEER_OUT"]) == (26, 70, 0)

    def test_neutral_pwm_is_1500_on_both_outputs(self):
        params = params_for(make_vessel(0, True))
        assert params["SERVO1_TRIM"] == params["SERVO3_TRIM"] == 1500


class TestGazeboHullGains:
    @pytest.fixture(params=sorted(VESSEL_SCALES))
    def hull(self, request):
        vessel = scaled_vessel(request.param)
        return vessel, derive_vessel_dynamics(vessel, 0.0, {}), VESSEL_SCALES[request.param].cruise_speed

    def test_the_turn_rate_feedforward_balances_the_yaw_damping_at_the_max_turn_rate(self, hull):
        vessel, dynamics, cruise = hull
        controls = gazebo_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        rate = vessel.max_angular_speed
        steering = controls.turn_rate_ff * rate
        moment = 2.0 * steering * dynamics.max_thrust * dynamics.thruster_y
        assert moment == pytest.approx(abs(dynamics.nR) * rate + abs(dynamics.nRabsR) * rate**2)
        assert 0.0 < steering < 1.0, "the max turn rate needs less than full differential thrust"

    def test_the_cruise_throttle_balances_the_surge_damping_at_the_cruise_speed(self, hull):
        vessel, dynamics, cruise = hull
        controls = gazebo_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        thrust = controls.cruise_throttle_percent / 100.0 * 2.0 * dynamics.max_thrust
        assert thrust == pytest.approx(abs(dynamics.xU) * cruise + abs(dynamics.xUabsU) * cruise**2)
        assert controls.top_speed == pytest.approx(dynamics.design_speed)

    def test_every_gain_is_positive_and_finite(self, hull):
        vessel, dynamics, cruise = hull
        controls = gazebo_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        for name in ("turn_rate_ff", "turn_rate_p", "turn_rate_i", "heading_p", "turn_accel_max_deg", "speed_p", "speed_i"):
            value = getattr(controls, name)
            assert math.isfinite(value) and value > 0, name

    def test_the_turn_acceleration_limit_is_what_full_differential_thrust_gives(self, hull):
        vessel, dynamics, cruise = hull
        controls = gazebo_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        full = 2.0 * dynamics.max_thrust * dynamics.thruster_y / (dynamics.hull_izz + abs(dynamics.nDotR))
        assert controls.turn_accel_max_deg == pytest.approx(math.degrees(full))

    def test_gazebo_params_carry_the_hull_gains(self):
        vessel = scaled_vessel("30m")
        params = params_for(vessel, layer=GAZEBO)
        controls = gazebo_control_parameters(derive_vessel_dynamics(vessel, 0.0, {}), vessel.max_angular_speed, 8.0)
        assert params["ATC_STR_RAT_FF"] == controls.turn_rate_ff
        assert params["ATC_STR_ANG_P"] == controls.heading_p
        assert params["ATC_SPEED_P"] == controls.speed_p
        assert params["ATC_STR_ACC_MAX"] == controls.turn_accel_max_deg
        assert params["CRUISE_THROTTLE"] == controls.cruise_throttle_percent

    def test_a_larger_hull_needs_more_steering_per_turn_rate(self):
        gains = [gazebo_control_parameters(derive_vessel_dynamics(scaled_vessel(scale), 0.0, {}), scaled_vessel(scale).max_angular_speed, 8.0).turn_rate_ff for scale in ("5m", "30m", "100m")]
        assert gains == sorted(gains)


class TestSitlMotorboatGains:
    @pytest.mark.parametrize("rate, speed", [(0.5, 3.0), (0.05, 8.0), (0.008, 8.0), (0.3, 0.8)])
    def test_rudder_steering_inverts_the_sitl_turn_rate(self, rate, speed):
        assert sitl_turn_rate(sitl_rudder_steering(rate, speed), speed) == pytest.approx(rate)

    def test_the_feedforward_turns_at_the_max_turn_rate_at_cruise_speed(self):
        controls = sitl_motorboat_control_parameters(0.5, 3.0)
        assert sitl_turn_rate(controls.turn_rate_ff * 0.5, 3.0) == pytest.approx(0.5)

    def test_the_cruise_throttle_balances_the_hull_drag(self):
        controls = sitl_motorboat_control_parameters(0.05, 8.0)
        assert controls.cruise_throttle_percent / 100.0 * SITL_THRUST_PER_THROTTLE_N == pytest.approx(SITL_HULL_DRAG_COEFFICIENT * 8.0**2)

    def test_the_speed_integral_follows_the_surge_time_constant(self):
        controls = sitl_motorboat_control_parameters(0.05, 8.0)
        surge_time_constant = SITL_BOAT_MASS_KG / (2 * SITL_HULL_DRAG_COEFFICIENT * 8.0)
        assert controls.speed_i == pytest.approx(controls.speed_p / surge_time_constant)

    def test_a_slow_cruise_keeps_the_throttle_inside_rovers_nudge_range(self):
        assert sitl_motorboat_control_parameters(0.5, 0.5).cruise_throttle_percent == 5.0


class TestWaypointGeometry:
    def test_waypoint_radius_is_clamped(self):
        assert params_for(make_vessel(0, True, length=0.5))["WP_RADIUS"] == 3.0
        assert params_for(make_vessel(0, True, length=1000.0))["WP_RADIUS"] == 150.0
        assert params_for(make_vessel(0, True, length=30.0))["WP_RADIUS"] == 120.0

    def test_overshoot_is_between_the_radius_and_200_meters(self):
        params = params_for(make_vessel(0, True, length=30.0, max_speed=20.0, max_angular_speed=0.05))
        assert params["WP_OVERSHOOT"] == 200.0
        small = params_for(make_vessel(0, True, length=30.0, max_speed=1.0, max_angular_speed=1.0))
        assert small["WP_OVERSHOOT"] == small["WP_RADIUS"]


def test_failsafes_and_arming_checks_are_disabled_for_simulation():
    params = params_for(make_vessel(0, True))
    for name in ("ARMING_CHECK", "ARMING_REQUIRE", "FS_GCS_ENABLE", "FS_THR_ENABLE", "FS_CRASH_CHECK", "FS_EKF_ACTION", "BAT_FS", "FS_ACTION"):
        assert params[name] == 0, name


def test_ardupilot_drives_no_kinematic_layer():
    with pytest.raises(ValueError, match="kinematic"):
        params_for(make_vessel(0, True), layer=SimulationLayerId.KINEMATIC)


class TestEnvironment:
    def test_calm_environment_parameters(self):
        params = params_for(make_vessel(0, True))
        assert params["SIM_WIND_SPD"] == 0
        assert params["SIM_WAVE_ENABLE"] == 0

    def test_wind_speed_is_the_vector_length(self):
        params = params_for(make_vessel(0, True), wind=np.array([3.0, 4.0, 0.0]))
        assert params["SIM_WIND_SPD"] == pytest.approx(5.0)

    def test_waves_enable_the_wave_parameters(self):
        wave = WaveConfig(amplitude=0.5, period=5.0, steepness=0.1, direction=np.array([0.0, 2.0]))
        params = params_for(make_vessel(0, True), wave=wave)
        assert params["SIM_WAVE_ENABLE"] == 1
        assert params["SIM_WAVE_AMP"] == 0.5
        assert params["SIM_WAVE_SPEED"] == 2.0
        assert params["SIM_WAVE_LENGTH"] == pytest.approx(10.0)
        assert params["SIM_WAVE_DIR"] == pytest.approx(90.0)
