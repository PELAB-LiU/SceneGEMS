"""derive_vessel_dynamics, hydrodynamics and thruster sizing: the parametric hull follows the vessel's dimensions."""

import dataclasses
import math

import pytest

from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import RHO_WATER, damping_force, split_damping, surge_damping
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.thrust_calculation import ardupilot_thrust_multiplier, size_thrusters
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import (
    ASSUMPTION_KEYS,
    BUOYANCY_GRID,
    OVERRIDE_KEYS,
    VALUE_KEYS,
    check_inertia,
    derive_vessel_dynamics,
)
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel

# The three scales of the Phase 2 manoeuvre checks (design doc 12.7): 5 m, 30 m and 100 m.
SCALES = {
    "5m": dict(length=5.0, max_speed=4.0, max_angular_speed=0.5, max_acceleration=1.0),
    "30m": dict(length=30.0, max_speed=20.57778, max_angular_speed=0.05, max_acceleration=0.4),
    "100m": dict(length=100.0, max_speed=12.9, max_angular_speed=0.008, max_acceleration=0.05),
}


@pytest.fixture(params=sorted(SCALES))
def vessel(request):
    return make_vessel(0, True, **SCALES[request.param])


class TestHull:
    def test_displacement_is_shared_by_hull_thrusters_and_windage(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        displacement = RHO_WATER * 0.6 * vessel.length * vessel.breadth * vessel.draft
        assert dynamics.total_mass == pytest.approx(displacement)

    def test_the_vessel_floats_at_its_design_draft(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.floating_draft == pytest.approx(vessel.draft, rel=1e-9)

    def test_the_buoyant_box_is_centered_on_the_waterline_and_reaches_one_draft_above(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.collision_z == 0.0
        assert dynamics.collision_height == pytest.approx(2 * vessel.draft)
        assert dynamics.keel_z == pytest.approx(-vessel.draft)

    def test_the_box_is_shrunk_by_the_block_coefficient(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.collision_length == pytest.approx(vessel.length * math.sqrt(0.6))
        assert dynamics.collision_breadth == pytest.approx(vessel.breadth * math.sqrt(0.6))

    def test_the_hull_is_stable_in_roll_and_pitch(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.roll_metacentric_height > 0
        assert dynamics.pitch_metacentric_height > 0

    def test_inertia_satisfies_the_triangle_inequality(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        check_inertia("hull", dynamics.hull_ixx, dynamics.hull_iyy, dynamics.hull_izz)

    def test_center_of_mass_is_half_a_draft_below_the_waterline(self, vessel):
        assert derive_vessel_dynamics(vessel).com_z == pytest.approx(-vessel.draft / 2)

    def test_buoyancy_grid_is_three_by_three(self):
        assert BUOYANCY_GRID == 3


class TestThrusters:
    def test_full_thrust_balances_the_damping_at_the_design_speed(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert 2 * dynamics.max_thrust == pytest.approx(damping_force(dynamics.xU, dynamics.xUabsU, 1.2 * vessel.max_speed))

    def test_design_speed_and_yaw_rate_have_a_twenty_percent_margin(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.design_speed == pytest.approx(1.2 * vessel.max_speed)
        assert dynamics.design_yaw_rate == pytest.approx(1.2 * vessel.max_angular_speed)

    def test_full_differential_thrust_balances_the_yaw_damping_at_the_design_yaw_rate(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        moment = 2 * dynamics.max_thrust * dynamics.thruster_y
        assert moment == pytest.approx(damping_force(dynamics.nR, dynamics.nRabsR, dynamics.design_yaw_rate))

    def test_thrusters_sit_aft_and_to_both_sides(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.thruster_x == pytest.approx(-0.45 * vessel.length)
        assert dynamics.thruster_y == pytest.approx(0.4 * vessel.breadth)

    def test_propeller_size_falls_back_to_the_draft_when_the_vessel_has_none(self):
        vessel = dataclasses.replace(make_vessel(0, True), _propeller_diameter=0.0, _motor_length=0.0)
        dynamics = derive_vessel_dynamics(vessel)
        assert dynamics.propeller_diameter == pytest.approx(0.6 * vessel.draft)
        assert dynamics.motor_length == pytest.approx(1.5 * dynamics.propeller_diameter)

    def test_size_thrusters_directly(self):
        sizing = size_thrusters(
            length=10.0,
            breadth=4.0,
            propeller_diameter=1.0,
            design_speed=5.0,
            xU=-10.0,
            xUabsU=-20.0,
            thruster_beam_ratio=0.5,
            thruster_aft_ratio=1.0,
            propeller_kt=0.3,
        )
        assert sizing.max_thrust == pytest.approx((10.0 * 5.0 + 20.0 * 25.0) / 2)
        assert sizing.thruster_x == -5.0
        assert sizing.thruster_y == 1.0
        assert sizing.thrust_coefficient == pytest.approx(0.3 / (2 * math.pi) ** 2)
        assert sizing.max_propeller_speed > 0

    def test_ardupilot_multiplier_spans_astern_to_ahead(self):
        assert ardupilot_thrust_multiplier(1000.0) == 2000.0


class TestHydrodynamics:
    def test_every_coefficient_opposes_the_motion(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        for name in ("xDotU", "yDotV", "zDotW", "nDotR", "xU", "yV", "zW", "kP", "mQ", "nR", "xUabsU", "yVabsV", "nRabsR"):
            assert getattr(dynamics, name) < 0, name

    def test_added_mass_stays_below_the_rigid_body_value(self, vessel):
        dynamics = derive_vessel_dynamics(vessel)
        displacement = dynamics.total_mass
        assert -dynamics.yDotV <= 0.5 * displacement + 1e-6
        assert -dynamics.zDotW <= 0.5 * displacement + 1e-6
        assert -dynamics.nDotR <= 0.5 * dynamics.hull_izz + 1e-6

    def test_surge_resistance_at_max_speed_uses_the_wetted_surface(self):
        linear, quadratic = surge_damping(length=10.0, breadth=4.0, draft=1.0, max_speed=5.0, resistance_coefficient=0.005, linear_damping_share=0.2)
        resistance = 0.5 * RHO_WATER * 0.005 * 10.0 * (4.0 + 2.0) * 25.0
        assert damping_force(linear, quadratic, 5.0) == pytest.approx(resistance)
        assert abs(linear) * 5.0 == pytest.approx(0.2 * resistance)

    def test_split_damping_sums_to_the_reference_damping(self):
        linear, quadratic = split_damping(100.0, 4.0, 0.25)
        assert abs(linear) * 4.0 + abs(quadratic) * 16.0 == pytest.approx(100.0)
        assert linear < 0 and quadratic < 0


class TestOverrides:
    def test_assumption_override_flows_into_the_derivation(self):
        vessel = make_vessel(0, True)
        base = derive_vessel_dynamics(vessel)
        denser = derive_vessel_dynamics(vessel, overrides={"block_coefficient": 0.75})
        assert denser.total_mass == pytest.approx(base.total_mass * 0.75 / 0.6)
        assert denser.floating_draft == pytest.approx(vessel.draft)

    def test_value_override_replaces_only_that_value(self):
        vessel = make_vessel(0, True)
        base = derive_vessel_dynamics(vessel)
        changed = derive_vessel_dynamics(vessel, overrides={"max_thrust": 12345.0})
        assert changed.max_thrust == 12345.0
        assert changed.hull_mass == base.hull_mass
        assert changed.xU == base.xU

    def test_overriding_the_hull_mass_changes_the_floating_draft(self):
        vessel = make_vessel(0, True)
        base = derive_vessel_dynamics(vessel)
        heavier = derive_vessel_dynamics(vessel, overrides={"hull_mass": base.hull_mass * 1.1})
        assert heavier.floating_draft > base.floating_draft

    def test_unknown_key_is_rejected_with_the_vessel(self):
        with pytest.raises(ValueError, match=r"vessel 0 \(OSPassengerShip\): unknown vessel dynamics keys \['colour'\]"):
            derive_vessel_dynamics(make_vessel(0, True), overrides={"colour": 1.0})

    def test_fixed_values_cannot_be_overridden(self):
        with pytest.raises(ValueError, match="unknown vessel dynamics keys"):
            derive_vessel_dynamics(make_vessel(0, True), overrides={"length": 1.0})

    def test_keys_are_assumptions_plus_values(self):
        assert OVERRIDE_KEYS == ASSUMPTION_KEYS | VALUE_KEYS
        assert not ASSUMPTION_KEYS & VALUE_KEYS


class TestValidation:
    def test_a_vessel_without_a_max_speed_is_rejected(self):
        with pytest.raises(ValueError, match="max speed and max angular speed must be positive"):
            derive_vessel_dynamics(make_vessel(0, True, max_speed=0.0))

    def test_a_vessel_that_cannot_turn_is_rejected(self):
        with pytest.raises(ValueError, match="max speed and max angular speed must be positive"):
            derive_vessel_dynamics(make_vessel(0, True, max_angular_speed=0.0))

    def test_a_mass_that_sinks_the_box_is_rejected(self):
        vessel = make_vessel(0, True)
        hull_mass = derive_vessel_dynamics(vessel).hull_mass
        with pytest.raises(ValueError, match="would sink"):
            derive_vessel_dynamics(vessel, overrides={"hull_mass": hull_mass * 3})

    def test_a_non_positive_mass_is_rejected(self):
        with pytest.raises(ValueError, match="hull_mass must be positive"):
            derive_vessel_dynamics(make_vessel(0, True), overrides={"hull_mass": -1.0})

    def test_a_hull_with_the_center_of_mass_above_the_waterline_is_rejected(self):
        # The roll stability check in _validate would explain this, but the hydrodynamics derivation
        # takes the square root of the (negative) roll stiffness first, so the error is a bare
        # "math domain error". Reported in the 12.5 results as an open point; only the rejection is pinned.
        with pytest.raises(ValueError):
            derive_vessel_dynamics(make_vessel(0, True), overrides={"com_depth_ratio": -3.0})

    def test_a_value_override_that_lifts_the_center_of_mass_makes_the_hull_unstable_in_roll(self):
        # com_z is a derived value: overriding it recomputes nothing, so the hydrodynamics are derived first and the check catches it.
        with pytest.raises(ValueError, match="unstable in roll"):
            derive_vessel_dynamics(make_vessel(0, True), overrides={"com_z": 5.0})

    def test_broken_inertia_is_rejected(self):
        with pytest.raises(ValueError, match="not a valid rigid body"):
            check_inertia("hull", 1.0, 1.0, 5.0)
        with pytest.raises(ValueError, match="not a valid rigid body"):
            check_inertia("hull", 0.0, 1.0, 1.0)
        check_inertia("hull", 2.0, 3.0, 4.0)


class TestWindage:
    def test_windage_mass_is_the_linearized_air_drag(self):
        vessel = make_vessel(0, True)
        calm = derive_vessel_dynamics(vessel, wind_speed=0.0)
        windy = derive_vessel_dynamics(vessel, wind_speed=10.0)
        assert windy.windage_mass == pytest.approx(calm.windage_mass * 10.0)
        side_area = vessel.length * (vessel.height - vessel.draft)
        assert calm.windage_mass == pytest.approx(0.5 * 1.225 * 0.9 * side_area * 1.0)

    def test_windage_does_not_change_the_total_mass(self):
        vessel = make_vessel(0, True)
        assert derive_vessel_dynamics(vessel, 0.0).total_mass == pytest.approx(derive_vessel_dynamics(vessel, 12.0).total_mass)
