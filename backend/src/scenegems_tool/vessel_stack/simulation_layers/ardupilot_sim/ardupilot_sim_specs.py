"""Specs of the ardupilot_sim simulation layer: the internal physics of ArduPilot SITL."""

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, EnvironmentSupport, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, LayerRef, SimulationLayerId

ARDUPILOT_SIM_LAYER = LayerSpec(
    layer=LayerRef.of(SimulationLayerId.ARDUPILOT_SIM),
    description="ArduPilot SITL's built-in motorboat physics, homed at the start pose of each vessel. No separate simulator container.",
    capabilities=Capabilities(wind=EnvironmentSupport.SUPPORTED, waves=EnvironmentSupport.UNMEASURED),
    restriction_notes=(("waves", "SITL receives the SIM_WAVE_* parameters, but their effect on a boat is not measured yet"),),
    provides_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
    requires_ports=frozenset({Port.ENVIRONMENT}),
)

SITL_INTERNAL_PHYSICS = AdapterSpec(
    id="sitl_internal_physics",
    source=LayerRef.of(ControlLayerId.ARDUPILOT),
    target=LayerRef.of(SimulationLayerId.ARDUPILOT_SIM),
    description="ArduPilot drives its own SITL physics in one process (SITL_SIMULATOR=ardupilot), paced by SITL --speedup.",
    # Bounded and unmeasured until measured; registry/measured_capabilities.yaml holds the values.
    capabilities=Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, max_speedup=None),
    provides_ports=frozenset({Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE}),
    built_in=True,
)
