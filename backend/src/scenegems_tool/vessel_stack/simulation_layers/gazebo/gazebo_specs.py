"""Specs of the Gazebo simulation layer and of the ArduPilot link into it."""

from typing import Optional

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, ContainerSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, LayerRef, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
from utils.file_system_utils import GAZEBO_ENTRYPOINT_CONTAINER_PATH

# True once the Gazebo image includes asv_wave_sim (gz-waves1). Then a world with waves replaces
# the flat Buoyancy system by a wave field, and each vessel model carries the wave-aware
# buoyancy system. Until then the waves capability stays unsupported and this stays False.
GAZEBO_WAVE_FORCES_AVAILABLE = False


def wave_forces_enabled(environment: Optional[EnvironmentConfig]) -> bool:
    """Whether the world and every vessel model use the asv_wave_sim wave field (decided once for both)."""
    return GAZEBO_WAVE_FORCES_AVAILABLE and environment is not None and environment.waves_requested


GAZEBO_CONTAINER = ContainerSpec(
    image="${GAZEBO_IMAGE:-scenegems-gazebo-harmonic:latest}",
    build_fingerprint_source="deploy/images/gazebo",
    entrypoint=GAZEBO_ENTRYPOINT_CONTAINER_PATH,
)

GAZEBO_LAYER = LayerSpec(
    layer=LayerRef.of(SimulationLayerId.GAZEBO),
    description="Gazebo Harmonic with a generated ocean world and one parametric twin-thrust SDF model per vessel (buoyancy, hydrodynamics, thrusters, WindEffects wind on a windage link).",
    capabilities=Capabilities(wind=EnvironmentSupport.SUPPORTED, waves=EnvironmentSupport.UNSUPPORTED),
    restriction_notes=(("waves", "Gazebo Harmonic has no wave force system; waves need asv_wave_sim in the Gazebo image (WP2 spike)"),),
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
