"""generate_vessel_model: the ArduPilot and custom variants, wind linearization and error cases."""

import numpy as np
import pytest

from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import generate_vessel_model
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel, wind_environment
from tests.scenegems_tool.vessel_stack.sdf import child_float, parse_sdf, plugins


@pytest.fixture
def vessel():
    return make_vessel(2, True)


def windage_mass(sdf_text: str) -> float:
    root = parse_sdf(sdf_text)
    (link,) = [link for link in root.iter("link") if link.get("name") == "windage_link"]
    return float(link.find("inertial/mass").text)


class TestVariants:
    def test_ardupilot_variant_carries_the_plugin_and_the_imu(self, vessel):
        root = parse_sdf(generate_vessel_model(vessel, "boat", ControlLayerId.ARDUPILOT))
        assert len(plugins(root, "ArduPilotPlugin")) == 1
        assert [sensor.get("name") for sensor in root.iter("sensor")] == ["imu_sensor"]

    def test_custom_variant_has_no_ardupilot_plugin_and_no_imu(self, vessel):
        root = parse_sdf(generate_vessel_model(vessel, "boat", ControlLayerId.CUSTOM))
        assert plugins(root, "ArduPilotPlugin") == []
        assert list(root.iter("sensor")) == []

    def test_both_variants_publish_odometry_and_accept_thrust(self, vessel):
        for control_layer in (ControlLayerId.ARDUPILOT, ControlLayerId.CUSTOM):
            root = parse_sdf(generate_vessel_model(vessel, "boat", control_layer))
            assert plugins(root, "gz-sim-odometry-publisher-system")
            assert len(plugins(root, "gz-sim-thruster-system")) == 2

    def test_odometry_publishes_at_fifty_hertz(self, vessel):
        root = parse_sdf(generate_vessel_model(vessel, "boat", ControlLayerId.CUSTOM))
        assert child_float(plugins(root, "gz-sim-odometry-publisher-system")[0], "odom_publish_frequency") == 50

    def test_other_control_layers_have_no_gazebo_model(self, vessel):
        with pytest.raises(ValueError, match="No Gazebo vessel model for control layer none"):
            generate_vessel_model(vessel, "boat", ControlLayerId.NONE)

    def test_the_model_and_topics_are_named_after_the_agent(self, vessel):
        text = generate_vessel_model(vessel, "unit_7", ControlLayerId.CUSTOM)
        assert parse_sdf(text).find("model").get("name") == "unit_7"
        assert "/model/unit_7/joint/motor_port_joint/cmd_thrust" in text
        assert "/model/unit_7/joint/motor_stbd_joint/cmd_thrust" in text

    def test_generation_is_deterministic(self, vessel):
        assert generate_vessel_model(vessel, "boat") == generate_vessel_model(vessel, "boat")


class TestEnvironment:
    def test_windage_follows_the_requested_wind_speed(self, vessel):
        calm = windage_mass(generate_vessel_model(vessel, "boat", environment=EnvironmentConfig.calm()))
        windy = windage_mass(generate_vessel_model(vessel, "boat", environment=wind_environment(0.0, 8.0)))
        assert windy == pytest.approx(calm * 8.0, rel=1e-3)

    def test_without_an_environment_the_windage_uses_the_reference_speed(self, vessel):
        assert windage_mass(generate_vessel_model(vessel, "boat")) == windage_mass(generate_vessel_model(vessel, "boat", environment=EnvironmentConfig.calm()))

    def test_waves_do_not_change_the_model_while_wave_forces_are_unavailable(self, vessel):
        from scenegems_tool.vessel_stack.contracts.vessel_stack_config import WaveConfig

        environment = EnvironmentConfig.calm()
        environment.wave = WaveConfig(amplitude=0.5, period=5.0, steepness=0.1, direction=np.array([1.0, 0.0]))
        assert generate_vessel_model(vessel, "boat", environment=environment) == generate_vessel_model(vessel, "boat")
        assert "gz-waves1" not in generate_vessel_model(vessel, "boat", environment=environment)


class TestOverrides:
    def test_explicit_overrides_replace_the_shipped_ones(self, vessel):
        text = generate_vessel_model(vessel, "boat", overrides={"max_thrust": 4321.0})
        limits = [child_float(plugin, "max_thrust_cmd") for plugin in plugins(parse_sdf(text), "gz-sim-thruster-system")]
        assert limits == [4321.0, 4321.0]

    def test_unknown_override_keys_fail_the_generation(self, vessel):
        with pytest.raises(ValueError, match="unknown vessel dynamics keys"):
            generate_vessel_model(vessel, "boat", overrides={"nonsense": 1.0})

    def test_the_shipped_override_files_apply_when_none_are_given(self, vessel, monkeypatch):
        from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators import vessel_model_generator
        from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics_overrides import VesselDynamicsOverrides

        monkeypatch.setattr(vessel_model_generator, "load_vessel_dynamics_overrides", lambda: VesselDynamicsOverrides(by_vessel_id={2: {"max_thrust": 777.0}}))
        text = generate_vessel_model(vessel, "boat")
        assert child_float(plugins(parse_sdf(text), "gz-sim-thruster-system")[0], "max_thrust_cmd") == 777.0
