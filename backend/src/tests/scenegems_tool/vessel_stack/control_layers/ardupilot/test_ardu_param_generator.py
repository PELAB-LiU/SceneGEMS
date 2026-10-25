"""generate_ardu_params: ArduPilot Rover parameters derived from the vessel's limits and the environment."""

import math

import numpy as np
import pytest

from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, WaveConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardu_param_generator import generate_ardu_params
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel

CALM = EnvironmentConfig.calm()


def params_for(vessel, cruise_speed=8.0, wind=None, wave=None):
    return generate_ardu_params(vessel, cruise_speed, CALM.wind_vector if wind is None else wind, CALM.wave if wave is None else wave)


def test_navigation_speeds_use_the_cruise_speed_and_absolute_limits_the_physical_max():
    params = params_for(make_vessel(0, True, max_speed=20.0), cruise_speed=8.0)
    assert params["WP_SPEED"] == params["WPNAV_SPEED"] == params["CRUISE_SPEED"] == 8.0
    assert params["SPEED_MAX"] == params["SIM_SHIP_SPEED"] == 20.0


def test_acceleration_limits_follow_the_vessel():
    params = params_for(make_vessel(0, True, max_acceleration=0.4))
    assert params["ATC_ACCEL_MAX"] == 0.4
    assert params["ATC_DECEL_MAX"] == pytest.approx(0.2)


def test_turn_rate_is_the_max_angular_speed_in_degrees():
    params = params_for(make_vessel(0, True, max_angular_speed=0.05))
    assert params["ATC_STR_RAT_MAX"] == pytest.approx(math.degrees(0.05))
    assert params["ATC_STR_ACC_MAX"] == pytest.approx(3 * math.degrees(0.05))


def test_rollover_protection_is_bypassed_with_at_least_one_g():
    assert params_for(make_vessel(0, True))["TURN_MAX_G"] >= 1.0
    # v^2 / (R g) with R = v / omega: a fast turner exceeds 1 g
    fast = make_vessel(0, True, max_speed=30.0, max_angular_speed=3.0)
    assert params_for(fast)["TURN_MAX_G"] == pytest.approx(30.0 * 3.0 / 9.81)


def test_waypoint_radius_is_clamped():
    assert params_for(make_vessel(0, True, length=0.5))["WP_RADIUS"] == 3.0
    assert params_for(make_vessel(0, True, length=1000.0))["WP_RADIUS"] == 150.0
    assert params_for(make_vessel(0, True, length=30.0))["WP_RADIUS"] == 120.0


def test_overshoot_is_between_the_radius_and_200_meters():
    params = params_for(make_vessel(0, True, length=30.0, max_speed=20.0, max_angular_speed=0.05))
    assert params["WP_OVERSHOOT"] == 200.0
    small = params_for(make_vessel(0, True, length=30.0, max_speed=1.0, max_angular_speed=1.0))
    assert small["WP_OVERSHOOT"] == small["WP_RADIUS"]


def test_a_vessel_that_cannot_turn_does_not_divide_by_zero():
    params = params_for(make_vessel(0, True, max_angular_speed=0.0))
    assert params["TURN_MAX_G"] >= 1.0
    assert params["ATC_STR_RAT_MAX"] == 0.0


def test_failsafes_and_arming_checks_are_disabled_for_simulation():
    params = params_for(make_vessel(0, True))
    for name in ("ARMING_CHECK", "ARMING_REQUIRE", "FS_GCS_ENABLE", "FS_THR_ENABLE", "FS_CRASH_CHECK", "FS_EKF_ACTION", "BAT_FS", "FS_ACTION"):
        assert params[name] == 0, name


def test_servo_functions_map_the_two_throttle_channels():
    params = params_for(make_vessel(0, True))
    assert (params["SERVO1_FUNCTION"], params["SERVO3_FUNCTION"]) == (73, 74)
    assert params["SKID_STEER_OUT"] == 1


def test_calm_environment_parameters():
    params = params_for(make_vessel(0, True))
    assert params["SIM_WIND_SPD"] == 0
    assert params["SIM_WAVE_ENABLE"] == 0


def test_wind_speed_is_the_vector_length():
    params = params_for(make_vessel(0, True), wind=np.array([3.0, 4.0, 0.0]))
    assert params["SIM_WIND_SPD"] == pytest.approx(5.0)


def test_waves_enable_the_wave_parameters():
    wave = WaveConfig(amplitude=0.5, period=5.0, steepness=0.1, direction=np.array([0.0, 2.0]))
    params = params_for(make_vessel(0, True), wave=wave)
    assert params["SIM_WAVE_ENABLE"] == 1
    assert params["SIM_WAVE_AMP"] == 0.5
    assert params["SIM_WAVE_SPEED"] == 2.0
    assert params["SIM_WAVE_LENGTH"] == pytest.approx(10.0)
    assert params["SIM_WAVE_DIR"] == pytest.approx(90.0)
