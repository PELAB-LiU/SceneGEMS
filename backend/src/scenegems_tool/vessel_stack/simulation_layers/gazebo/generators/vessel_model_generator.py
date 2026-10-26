"""SDF of one generated vessel: a parametric twin-thrust hull (vessel_dynamics.py) in one of two variants.

- control layer ardupilot: the ArduPilotPlugin turns SITL servo outputs into thrust commands
  (JSON lockstep backend) and reads the IMU.
- control layer custom: no ArduPilotPlugin. A controller publishes gz.msgs.Double thrust in N on
  /model/<name>/joint/motor_port_joint/cmd_thrust and .../motor_stbd_joint/cmd_thrust, and reads
  gz.msgs.Odometry on /model/<name>/odometry.
"""

import math
from typing import Mapping, Optional, Tuple

import numpy as np

from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, WaveConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import wave_forces_enabled
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.thrust_calculation import ardupilot_thrust_multiplier
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import BUOYANCY_GRID, VesselDynamics, derive_vessel_dynamics
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics_overrides import load_vessel_dynamics_overrides

GAZEBO_MODEL_CONTROL_LAYERS = (ControlLayerId.ARDUPILOT, ControlLayerId.CUSTOM)
ODOMETRY_RATE_HZ = 50
# Under waves the wave-aware buoyancy reads the wave height at the corners of each collision box's
# faces, so a box as long as a wave sees a flat sea. Cells of at most 1/WAVE_CELLS_PER_WAVELENGTH of
# the wavelength let the hull heave and pitch with the wave (the WP2 spike's 3 by 3 cells were too
# coarse for the 30 and 100 m hulls in 5 s waves), up to MAX_WAVE_CELLS per side to bound the cost.
WAVE_CELLS_PER_WAVELENGTH = 8
MAX_WAVE_CELLS = 24
GRAVITY = 9.81


def _f(value: float) -> str:
    """Plain decimal with up to 6 significant digits (no exponent, which keeps the SDF readable)."""
    return np.format_float_positional(float(value), precision=6, unique=False, fractional=False, trim="-")


def sdf_value(value: float) -> float:
    """The value Gazebo reads back from the SDF: rounded as _f writes it."""
    return float(_f(value))


def _inertia(ixx: float, iyy: float, izz: float) -> str:
    return f"<ixx>{_f(ixx)}</ixx><iyy>{_f(iyy)}</iyy><izz>{_f(izz)}</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz>"


def generate_vessel_model(
    vessel: ConcreteVessel,
    agent_name: str,
    control_layer: ControlLayerId = ControlLayerId.ARDUPILOT,
    environment: Optional[EnvironmentConfig] = None,
    overrides: Optional[Mapping[str, float]] = None,
) -> str:
    """Model of one vessel. The environment sets the windage linearization and whether the hull carries
    the wave-aware buoyancy; overrides default to the vessel_dynamics files' entries for this vessel."""
    if overrides is None:
        overrides = load_vessel_dynamics_overrides().for_vessel(vessel)
    wind_speed = float(np.linalg.norm(environment.wind_vector)) if environment is not None else 0.0
    dynamics = derive_vessel_dynamics(vessel, wind_speed, overrides)
    wave = environment.wave if wave_forces_enabled(environment) else None
    return render_vessel_model(dynamics, agent_name, int(vessel.id), control_layer, wave)


def deep_water_wavelength(period: float) -> float:
    return GRAVITY * period**2 / (2.0 * math.pi)


def buoyancy_cells(d: VesselDynamics, wave: Optional[WaveConfig] = None) -> Tuple[int, int]:
    """Buoyancy cells along and across the hull: BUOYANCY_GRID each in flat water, finer under waves."""
    if wave is None:
        return BUOYANCY_GRID, BUOYANCY_GRID
    cell = deep_water_wavelength(wave.period) / WAVE_CELLS_PER_WAVELENGTH

    def count(extent: float) -> int:
        return int(min(max(math.ceil(extent / cell), BUOYANCY_GRID), MAX_WAVE_CELLS))

    return count(d.collision_length), count(d.collision_breadth)


def render_vessel_model(d: VesselDynamics, agent_name: str, vessel_id: int, control_layer: ControlLayerId, wave: Optional[WaveConfig] = None) -> str:
    """wave: the wave field the hull floats in (wave forces on), None for flat water."""
    if control_layer not in GAZEBO_MODEL_CONTROL_LAYERS:
        raise ValueError(f"No Gazebo vessel model for control layer {control_layer.value}; supported: {[layer.value for layer in GAZEBO_MODEL_CONTROL_LAYERS]}")
    ardupilot = control_layer == ControlLayerId.ARDUPILOT
    freeboard = d.height - d.draft
    thruster_radius = d.propeller_diameter / 2.0
    thruster_ixx = 0.5 * d.thruster_mass * thruster_radius**2
    thruster_iyy = d.thruster_mass / 12.0 * (3.0 * thruster_radius**2 + d.motor_length**2)
    windage_ixx = d.windage_mass / 12.0 * (d.breadth**2 + freeboard**2)
    windage_iyy = d.windage_mass / 12.0 * (d.length**2 + freeboard**2)
    windage_izz = d.windage_mass / 12.0 * (d.length**2 + d.breadth**2)

    cells_along, cells_across = buoyancy_cells(d, wave)
    cell_length, cell_breadth = d.collision_length / cells_along, d.collision_breadth / cells_across
    along = [(i - (cells_along - 1) / 2.0) for i in range(cells_along)]
    across = [(j - (cells_across - 1) / 2.0) for j in range(cells_across)]
    collisions = "".join(f"""
      <collision name="collision_hull_{i}_{j}">
        <pose>{_f(dx * cell_length)} {_f(dy * cell_breadth)} {_f(d.collision_z)} 0 0 0</pose>
        <geometry>
          <box>
            <size>{_f(cell_length)} {_f(cell_breadth)} {_f(d.collision_height)}</size>
          </box>
        </geometry>
      </collision>""" for i, dx in enumerate(along) for j, dy in enumerate(across))

    imu_sensor = (
        """
      <sensor name="imu_sensor" type="imu">
        <pose degrees="true">0 0 0 180 0 0</pose>
        <always_on>1</always_on>
        <update_rate>100.0</update_rate>
      </sensor>"""
        if ardupilot
        else ""
    )

    def thruster(side: str, y: float) -> str:
        return f"""
    <link name="motor_{side}_link">
      <pose>{_f(d.thruster_x)} {_f(y)} {_f(d.thruster_z)} 0 0 0</pose>
      <inertial>
        <mass>{_f(d.thruster_mass)}</mass>
        <inertia>{_inertia(thruster_ixx, thruster_iyy, thruster_iyy)}</inertia>
      </inertial>
    </link>
    <joint name="motor_{side}_joint" type="revolute">
      <parent>base_link</parent>
      <child>motor_{side}_link</child>
      <axis>
        <xyz>1 0 0</xyz> <!-- thrust direction for the Thruster system -->
      </axis>
    </joint>
    <plugin filename="gz-sim-thruster-system" name="gz::sim::systems::Thruster">
      <joint_name>motor_{side}_joint</joint_name>
      <thrust_coefficient>{_f(d.thrust_coefficient)}</thrust_coefficient>
      <fluid_density>1025</fluid_density>
      <propeller_diameter>{_f(d.propeller_diameter)}</propeller_diameter>
      <!-- The propeller turns at the speed of the thrust (no propeller PID torque on the hull), and the
           system publishes that speed on .../ang_vel every iteration: the gz-transport actuator checks
           with it that a thrust command was in effect from the step's first iteration. -->
      <velocity_control>1</velocity_control>
      <use_angvel_cmd>0</use_angvel_cmd>
      <max_thrust_cmd>{_f(d.max_thrust)}</max_thrust_cmd>
      <min_thrust_cmd>{_f(-d.max_thrust)}</min_thrust_cmd>
    </plugin>"""

    wave_buoyancy = (
        f"""

    <!-- Wave-aware buoyancy (asv_wave_sim, its system renamed WavesHydrodynamics in the Gazebo image so it
         loads next to the gz-sim Hydrodynamics system, which keeps the damping and added mass). -->
    <plugin filename="gz-waves1-hydrodynamics-system" name="gz::sim::systems::WavesHydrodynamics">
      <enable>{agent_name}::base_link</enable>
      <hydrodynamics>
        <damping_on>0</damping_on>
        <viscous_drag_on>0</viscous_drag_on>
        <pressure_drag_on>0</pressure_drag_on>
      </hydrodynamics>
    </plugin>"""
        if wave is not None
        else ""
    )

    ardupilot_plugin = ""
    if ardupilot:
        fdm_port_in = 9000 + vessel_id * 10 + 2
        multiplier = _f(ardupilot_thrust_multiplier(d.max_thrust))
        ardupilot_plugin = f"""
    <plugin filename="ArduPilotPlugin" name="ArduPilotPlugin">
      <robotNamespace>{agent_name}</robotNamespace>
      <connectionTimeoutMaxCount>5</connectionTimeoutMaxCount>
      <lock_step>1</lock_step>
      <fdm_addr>0.0.0.0</fdm_addr>
      <fdm_port_in>{fdm_port_in}</fdm_port_in>
      <!-- Match ardupilot_gazebo iris: ENU world + FLU hull to NED / aircraft body. -->
      <modelXYZToAirplaneXForwardZDown>0 0 0 3.141592653589793 0 0</modelXYZToAirplaneXForwardZDown>
      <gazeboXYZToNED>0 0 0 3.141592653589793 0 1.5707963267948966</gazeboXYZToNED>
      <imuName>imu_sensor</imuName>
      <!-- Port motor, SERVO1_FUNCTION 73 (ThrottleLeft). PWM 1000 to 2000 is full astern to full ahead. -->
      <control channel="0">
        <jointName>motor_port_joint</jointName>
        <type>COMMAND</type>
        <cmd_topic>/model/{agent_name}/joint/motor_port_joint/cmd_thrust</cmd_topic>
        <multiplier>{multiplier}</multiplier>
        <offset>-0.5</offset>
        <servo_min>1000</servo_min>
        <servo_max>2000</servo_max>
      </control>
      <!-- Starboard motor, SERVO3_FUNCTION 74 (ThrottleRight). -->
      <control channel="2">
        <jointName>motor_stbd_joint</jointName>
        <type>COMMAND</type>
        <cmd_topic>/model/{agent_name}/joint/motor_stbd_joint/cmd_thrust</cmd_topic>
        <multiplier>{multiplier}</multiplier>
        <offset>-0.5</offset>
        <servo_min>1000</servo_min>
        <servo_max>2000</servo_max>
      </control>
    </plugin>"""

    return f"""<?xml version="1.0"?>
<sdf version="1.9">
  <!-- Parametric twin-thrust vessel, control layer {control_layer.value}: L {_f(d.length)} m, B {_f(d.breadth)} m,
       draft {_f(d.draft)} m, {_f(d.total_mass)} kg, full thrust {_f(d.max_thrust)} N per thruster for {_f(d.design_speed)} m/s,
       full differential thrust for {_f(d.design_yaw_rate)} rad/s. Thrust commands: gz.msgs.Double in N on
       /model/{agent_name}/joint/motor_port_joint/cmd_thrust and /model/{agent_name}/joint/motor_stbd_joint/cmd_thrust. -->
  <model name="{agent_name}">
    <self_collide>false</self_collide>
    <!-- Avoid links auto-disabling mid-run (can destabilize coupled buoyancy/hydro). -->
    <allow_auto_disable>false</allow_auto_disable>
    <static>false</static>
    <!-- Pose is applied by the world via <include><pose> so this model stays reusable. Origin at the waterline. -->

    <link name="base_link">
      <inertial>
        <pose>0 0 {_f(d.com_z)} 0 0 0</pose>
        <mass>{_f(d.hull_mass)}</mass>
        <inertia>{_inertia(d.hull_ixx, d.hull_iyy, d.hull_izz)}</inertia>
      </inertial>
      <!-- Buoyant volume: displaces the total mass at the draft (world Buoyancy system), split into
           {BUOYANCY_GRID} x {BUOYANCY_GRID} cells so that roll and pitch are restored (see vessel_dynamics.BUOYANCY_GRID). -->{collisions}
      <visual name="visual_hull">
        <pose>0 0 {_f((freeboard - d.draft) / 2.0)} 0 0 0</pose>
        <geometry>
          <box>
            <size>{_f(d.length)} {_f(d.breadth)} {_f(d.height)}</size>
          </box>
        </geometry>
      </visual>{imu_sensor}
    </link>

    <!-- Windage: the world WindEffects system pushes this link with mass * factor * relative wind,
         so its mass is the hull's air drag in N per m/s. Fixed to the hull at the center of the side area above water. -->
    <link name="windage_link">
      <pose>0 0 {_f(d.windage_z)} 0 0 0</pose>
      <enable_wind>true</enable_wind>
      <inertial>
        <mass>{_f(d.windage_mass)}</mass>
        <inertia>{_inertia(windage_ixx, windage_iyy, windage_izz)}</inertia>
      </inertial>
    </link>
    <joint name="windage_joint" type="fixed">
      <parent>base_link</parent>
      <child>windage_link</child>
    </joint>
{thruster("port", d.thruster_y)}
{thruster("stbd", -d.thruster_y)}

    <!-- Added-mass Coriolis terms off: their Munk moment makes a bare hull directionally unstable
         (measured: the 5 m hull spun under equal thrust above 2.5 m/s); real twin-screw hulls are kept
         straight by skegs, which this model does not have. -->
    <plugin filename="gz-sim-hydrodynamics-system" name="gz::sim::systems::Hydrodynamics">
      <link_name>base_link</link_name>
      <disable_coriolis>true</disable_coriolis>
      <xDotU>{_f(d.xDotU)}</xDotU>
      <yDotV>{_f(d.yDotV)}</yDotV>
      <zDotW>{_f(d.zDotW)}</zDotW>
      <nDotR>{_f(d.nDotR)}</nDotR>
      <xU>{_f(d.xU)}</xU>
      <yV>{_f(d.yV)}</yV>
      <zW>{_f(d.zW)}</zW>
      <kP>{_f(d.kP)}</kP>
      <mQ>{_f(d.mQ)}</mQ>
      <nR>{_f(d.nR)}</nR>
      <xUabsU>{_f(d.xUabsU)}</xUabsU>
      <yVabsV>{_f(d.yVabsV)}</yVabsV>
      <nRabsR>{_f(d.nRabsR)}</nRabsR>
    </plugin>{wave_buoyancy}

    <plugin filename="gz-sim-joint-state-publisher-system" name="gz::sim::systems::JointStatePublisher">
    </plugin>

    <plugin filename="gz-sim-odometry-publisher-system" name="gz::sim::systems::OdometryPublisher">
      <odom_frame>odom</odom_frame>
      <robot_base_frame>base_link</robot_base_frame>
      <dimensions>3</dimensions>
      <odom_publish_frequency>{ODOMETRY_RATE_HZ}</odom_publish_frequency>
    </plugin>{ardupilot_plugin}
  </model>
</sdf>
"""
