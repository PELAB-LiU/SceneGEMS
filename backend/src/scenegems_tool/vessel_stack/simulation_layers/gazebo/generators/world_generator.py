# flake8: noqa: W293
from typing import List, Tuple

import numpy as np

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import WaveConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import WIND_FORCE_SCALING
from utils.global_constants import MAX_COORD

PHYSICS_STEP_S = 0.005  # max_step_size of the world; a runner that steps the world counts iterations of it


def _vessel_include(uri: str, state: ActorState) -> str:
    """Include a generated vessel model by URI and place it via the world (model stays pose-free)."""
    return f"""    <include>
      <uri>{uri}</uri>
      <pose>{state.x} {state.y} 0 0 0 {state.heading}</pose>
    </include>"""


def _waves_block(wave: WaveConfig) -> str:
    """Regular waves from asv_wave_sim (gz-waves1). Gazebo Harmonic itself has no wave force system."""
    direction = np.asarray(wave.direction, dtype=float) / max(float(np.linalg.norm(wave.direction)), 1e-9)
    return f"""
    <!-- Wave field (asv_wave_sim gz-waves1, regular sinusoid). Every vessel model carries the wave-aware
         buoyancy system, so the flat Buoyancy system is not loaded. The wavelength follows the period by
         deep-water dispersion; the WaveConfig speed and steepness are not used. -->
    <model name="waves">
      <static>true</static>
      <plugin filename="gz-waves1-waves-model-system" name="gz::sim::systems::WavesModel">
        <static>0</static>
        <update_rate>30</update_rate>
        <wave>
          <tile_size>1024</tile_size>
          <cell_count>128</cell_count>
          <algorithm>sinusoid</algorithm>
          <amplitude>{wave.amplitude}</amplitude>
          <period>{wave.period}</period>
          <direction>{direction[0]} {direction[1]}</direction>
        </wave>
      </plugin>
      <link name="base_link"/>
    </model>"""


def generate_world(
    center: np.ndarray,
    vessel_includes: List[Tuple[str, ActorState]],
    wind_vector: np.ndarray,
    wave: WaveConfig,
    speed_factor: int,
    headless: bool,
    wave_forces: bool = False,
    externally_stepped: bool = False,
) -> str:
    """The ocean world; wave_forces (gazebo_specs.wave_forces_enabled) swaps flat buoyancy for the asv_wave_sim wave field.

    externally_stepped: a runner steps the paused world (gz_transport_actuator.py), so the real
    time factor is 0 and gz-sim runs each requested iteration as fast as it can.
    """
    real_time_factor = 0 if externally_stepped else speed_factor
    vessel_block = "\n".join(_vessel_include(uri, state) for uri, state in vessel_includes)

    scene_broadcaster_block = (
        """
    <plugin filename="gz-sim-scene-broadcaster-system"
      name="gz::sim::systems::SceneBroadcaster">
    </plugin>
    """
        if not headless
        else ""
    )

    buoyancy_block = """
    <!-- Buoyancy at flat sea level (z=0); visual water is static mesh below (no Waves system). -->
    <plugin filename="gz-sim-buoyancy-system" name="gz::sim::systems::Buoyancy">
      <graded_buoyancy>
        <default_density>1025</default_density>
        <density_change>
          <above_depth>0</above_depth>
          <density>1.225</density>
          <!-- Air density -->
        </density_change>
      </graded_buoyancy>
      <enable_water_velocity>true</enable_water_velocity>
    </plugin>
    """

    world_template = f"""
    

<?xml version="1.0" ?>
<sdf version="1.9">
<world name="ocean_world">
    <!-- DART defaults to ODE collision; ODE can abort with aabbBound asserts on some
         multi-link / buoyancy-heavy setups. Use Bullet broadphase for collision detection. -->
    <physics name="1ms" type="ignored">
    <!-- Slightly smaller step helps constraint-heavy marine models (thrusters + buoyancy + hydro). -->
    <max_step_size>{PHYSICS_STEP_S}</max_step_size>
    <real_time_factor>{real_time_factor}</real_time_factor>
    <!-- <dart> 
      <collision_detector>bullet</collision_detector>
      <solver>
        <solver_type>pgs</solver_type>
      </solver>
    </dart>-->
    </physics>
    
    <plugin filename="gz-sim-physics-system"
      name="gz::sim::systems::Physics">
    </plugin>
    <plugin
      filename="gz-sim-sensors-system"
      name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
      <background_color>0.8 0.8 0.8</background_color>
    </plugin>
    <plugin filename="gz-sim-user-commands-system"
      name="gz::sim::systems::UserCommands">
    </plugin>
    {scene_broadcaster_block}
    <plugin filename="gz-sim-imu-system"
      name="gz::sim::systems::Imu">
    </plugin>
    <plugin filename="gz-sim-navsat-system"
      name="gz::sim::systems::NavSat">
    </plugin>
    <plugin name="gz::sim::systems::Anemometer"
      filename="asv_sim2-anemometer-system">
    </plugin>
    <gravity>0 0 -9.81</gravity>
    
    <spherical_coordinates>
        <surface_model>EARTH_WGS84</surface_model>

        <latitude_deg>{center[0]}</latitude_deg>
        <longitude_deg>{center[1]}</longitude_deg>

        <elevation>0</elevation>
        <heading_deg>0</heading_deg>
    </spherical_coordinates>
    

    <plugin filename="asv_sim2-wind-system"
      name="gz::sim::systems::Wind">
      <topic>/wind</topic>
    </plugin>

    <!-- Wind force on links with enable_wind (each vessel's windage link): mass * factor *
         (wind velocity - link velocity), wind from the <wind> element below. This system sets
         the wind every step, so change it at runtime on /world/ocean_world/wind (gz.msgs.Wind),
         not on the asv_sim2 /wind topic. -->
    <plugin filename="gz-sim-wind-effects-system"
      name="gz::sim::systems::WindEffects">
      <force_approximation_scaling_factor>{WIND_FORCE_SCALING}</force_approximation_scaling_factor>
    </plugin>


    {_waves_block(wave) if wave_forces else buoyancy_block}


    <scene>
        <ambient>0.8 0.8 0.8 1</ambient>
        <background>0.5 0.7 0.9 1</background>
        <grid>false</grid>
        <sky></sky>
    </scene>


    <light type="directional" name="sun">
        <cast_shadows>true</cast_shadows>
        <pose>0 0 100 0 0 0</pose>
        <diffuse>1 1 1 1</diffuse>
        <specular>0.5 0.5 0.5 1</specular>
        <direction>-0.5 0.1 -0.9</direction>
    </light>


    <!-- Static sea surface: large plane mesh, visual only (no collision). -->
    <model name="water_surface">
    <static>true</static>
    <pose>0 0 0 0 0 0</pose>
    <link name="water_link">
        <visual name="water_visual">
        <pose>0 0 0 0 0 0</pose>
        <transparency>0.25</transparency>
        <geometry>
            <plane>
            <normal>0 0 1</normal>
            <!-- size: meters (full width and height of the plane) -->
            <size>{MAX_COORD} {MAX_COORD}</size>
            </plane>
        </geometry>
        <material>
            <ambient>0.05 0.28 0.42 0.85</ambient>
            <diffuse>0.08 0.38 0.58 0.8</diffuse>
            <specular>0.6 0.65 0.7 1</specular>
            <emissive>0 0 0 1</emissive>
        </material>
        </visual>
    </link>
    </model>
    <!-- Global Wind -->
    <wind>
    <linear_velocity>{wind_vector[0]} {wind_vector[1]} {wind_vector[2]}</linear_velocity>
    </wind>
    
    <!-- Vessel Models -->
    {vessel_block}
</world>
</sdf>
    """
    return world_template
