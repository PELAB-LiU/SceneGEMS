"""generate_world: plugins, wind, waves and vessel placement of the ocean world."""

import numpy as np
import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, WaveConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.world_generator import generate_world
from tests.scenegems_tool.vessel_stack.sdf import child_float, parse_sdf, plugins

CENTER = np.array([57.0, 16.0])
INCLUDES = [("/models/a.sdf", ActorState(1.0, 2.0, 3.0, 0.5))]


def world(*, wind=None, wave=None, speed_factor=1, headless=True, wave_forces=False, externally_stepped=False):
    calm = EnvironmentConfig.calm()
    return parse_sdf(
        generate_world(CENTER, INCLUDES, calm.wind_vector if wind is None else wind, calm.wave if wave is None else wave, speed_factor, headless, wave_forces, externally_stepped=externally_stepped)
    )


def regular_waves() -> WaveConfig:
    return WaveConfig(amplitude=0.4, period=6.0, steepness=0.1, direction=np.array([2.0, 0.0]))


def test_default_plugins_are_loaded():
    root = world()
    for filename in (
        "gz-sim-physics-system",
        "gz-sim-sensors-system",
        "gz-sim-user-commands-system",
        "gz-sim-imu-system",
        "gz-sim-navsat-system",
        "gz-sim-wind-effects-system",
        "gz-sim-buoyancy-system",
    ):
        assert len(plugins(root, filename)) == 1, filename


def test_headless_has_no_scene_broadcaster_and_gui_has_one():
    assert plugins(world(headless=True), "gz-sim-scene-broadcaster-system") == []
    assert len(plugins(world(headless=False), "gz-sim-scene-broadcaster-system")) == 1


@pytest.mark.parametrize("factor", [1, 2, 8])
def test_speed_factor_sets_the_real_time_factor(factor):
    assert child_float(world(speed_factor=factor).find("world/physics"), "real_time_factor") == factor


def test_an_externally_stepped_world_runs_without_a_real_time_factor():
    """The runner paces the world through the actuator; gz sim must not hold its iterations back to a wall clock."""
    root = world(speed_factor=8, externally_stepped=True)
    assert child_float(root.find("world/physics"), "real_time_factor") == 0.0
    assert child_float(root.find("world/physics"), "max_step_size") == 0.005


def test_wind_vector_is_written_verbatim():
    assert world(wind=np.array([1.5, -2.0, 0.0])).find("world/wind/linear_velocity").text == "1.5 -2.0 0.0"


def test_includes_place_each_vessel_at_its_state():
    include = world().find("world/include")
    assert include.find("uri").text == "/models/a.sdf"
    assert include.find("pose").text == "1.0 2.0 0 0 0 0.5"


def test_reference_point_is_the_center():
    coordinates = world().find("world/spherical_coordinates")
    assert float(coordinates.find("latitude_deg").text) == 57.0
    assert float(coordinates.find("longitude_deg").text) == 16.0


def test_flat_buoyancy_world_has_no_wave_model():
    root = world(wave=regular_waves(), wave_forces=False)
    assert len(plugins(root, "gz-sim-buoyancy-system")) == 1
    assert plugins(root, "gz-waves1-waves-model-system") == []


def test_wave_forces_replace_flat_buoyancy_by_the_wave_field():
    root = world(wave=regular_waves(), wave_forces=True)
    assert plugins(root, "gz-sim-buoyancy-system") == []
    (waves,) = plugins(root, "gz-waves1-waves-model-system")
    assert child_float(waves.find("wave"), "amplitude") == 0.4
    assert child_float(waves.find("wave"), "period") == 6.0
    assert waves.find("wave/direction").text == "1.0 0.0", "the direction is normalized"


def test_water_surface_is_a_visual_only_static_model():
    (surface,) = [model for model in world().iter("model") if model.get("name") == "water_surface"]
    assert surface.find("static").text == "true"
    assert list(surface.iter("collision")) == []
