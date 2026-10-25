"""Reference vessels and trajectories of the measurements."""

import math

import pytest

from scenegems_tool.vessel_stack.calibration.reference_scenarios import (
    ENCOUNTER_TARGETS,
    VESSEL_SCALES,
    encounter_trajectories,
    reference_run,
    scaled_vessel,
    straight_run,
    turning_run,
)


def test_scales_are_the_three_hulls_of_the_manoeuvre_checks():
    assert {name: spec.length for name, spec in VESSEL_SCALES.items()} == {"5m": 5.0, "30m": 30.0, "100m": 100.0}


def test_scaled_vessel_carries_the_limits_of_its_scale():
    vessel = scaled_vessel("30m", vessel_id=3, is_os=False)
    assert (vessel.id, vessel.length, vessel.is_os) == (3, 30.0, False)
    assert vessel.max_speed == pytest.approx(20.57778)
    assert vessel.max_angular_speed == 0.05


def test_straight_run_goes_east_at_the_cruise_speed():
    trajectories = straight_run("5m", 60)
    states = trajectories.state_list(trajectories.initial_scene.os)
    assert len(states) == 61
    assert states[-1].x == pytest.approx(3.0 * 60)
    assert states[-1].y == pytest.approx(0.0)


def test_turning_run_turns_left_and_back():
    trajectories = turning_run("5m", 120)
    states = trajectories.state_list(trajectories.initial_scene.os)
    headings = [state.heading for state in states]
    assert headings[0] == 0.0
    assert max(headings) == pytest.approx(math.pi / 2)
    assert headings[-1] == pytest.approx(0.0)
    assert states[-1].y > 100.0, "the vessel ends up north of where it started"


def test_turning_run_is_reproducible():
    assert turning_run("5m", 60).to_dict() == turning_run("5m", 60).to_dict()


def test_encounter_has_the_own_ship_at_the_origin_and_one_target():
    for name, target in ENCOUNTER_TARGETS.items():
        scene = encounter_trajectories(name, 10).initial_scene
        assert len(scene.vessels) == 2
        assert (scene.os_state.x, scene.os_state.y) == (0.0, 0.0)
        assert scene[scene.actors[1]].x == target.x


def test_reference_run_dispatch():
    assert len(reference_run("straight", "5m", 30)) == 31
    assert len(reference_run("turning", "5m", 30)) == 31
    with pytest.raises(ValueError, match="Unknown reference run 'loop'"):
        reference_run("loop")
