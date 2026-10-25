"""Specs of the Gazebo simulation layer and of the ArduPilot link into it."""

from scenegems_tool.vessel_stack.contracts.adapter_spec import UPSTREAM_PINS_FILE, AdapterSpec, ContainerSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, LayerRef, SimulationLayerId
from utils.file_system_utils import GAZEBO_ENTRYPOINT_CONTAINER_PATH

GAZEBO_CONTAINER = ContainerSpec(
    image="${GAZEBO_IMAGE:-scenegems-gazebo-harmonic:latest}",
    build_fingerprint_source="deploy/images/gazebo",
    entrypoint=GAZEBO_ENTRYPOINT_CONTAINER_PATH,
    upstream_pins_file=UPSTREAM_PINS_FILE,
)

GAZEBO_LAYER = LayerSpec(
    layer=LayerRef.of(SimulationLayerId.GAZEBO),
    description="Gazebo Harmonic with a generated ocean world and one generated SDF model per vessel (buoyancy, hydrodynamics, thrusters, asv_sim2 wind).",
    capabilities=Capabilities(wind=EnvironmentSupport.SUPPORTED, waves=EnvironmentSupport.UNSUPPORTED),
    restriction_notes=(("waves", "the Gazebo waves system is commented out in world_generator.py and is not enabled yet"),),
    provides_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
    requires_ports=frozenset({Port.ACTUATOR_CMD, Port.ENVIRONMENT}),
    containers=(GAZEBO_CONTAINER,),
)

ARDUPILOT_GAZEBO_PLUGIN = AdapterSpec(
    id="ardupilot_gazebo_plugin",
    source=LayerRef.of(ControlLayerId.ARDUPILOT),
    target=LayerRef.of(SimulationLayerId.GAZEBO),
    description="SITL with the JSON backend, linked to the ArduPilotPlugin of each generated vessel model (lock_step 1, thrust commands on the motor joints).",
    # Bounded and unmeasured until Phase 0 measures it; measured values replace these from
    # registry/measured_capabilities.yaml.
    capabilities=Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, max_speedup=None),
    provides_ports=frozenset({Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)
