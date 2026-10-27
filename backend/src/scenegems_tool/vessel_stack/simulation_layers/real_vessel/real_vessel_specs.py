"""Specs of the real_vessel simulation layer: the physical vessel in the water, and its built-in autopilot adapter.

The real vessel is not part of the simulation instance: it moves on its own, in the real
weather, and joins the instance's other vessels over MQTT. Its control layer is its own
autopilot (control_layers/real_vessel/real_vessel_specs.py).
"""

import dataclasses

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import EnvironmentSupport
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, LayerRef, SimulationLayerId
from scenegems_tool.vessel_stack.control_layers.real_vessel.real_vessel_specs import REAL_VESSEL_CAPABILITIES, REAL_VESSEL_INTERACTIVE_NOTE

_REAL_WEATHER_NOTE = "a real vessel meets the real weather; requested wind and waves apply to the simulated vessels only"

REAL_VESSEL_SIMULATION_LAYER = LayerSpec(
    layer=LayerRef.of(SimulationLayerId.REAL_VESSEL),
    description="The physical vessel in the water: its own hull, sensors and weather, on the wall clock. It joins the simulated vessels over MQTT.",
    capabilities=dataclasses.replace(REAL_VESSEL_CAPABILITIES, wind=EnvironmentSupport.UNSUPPORTED, waves=EnvironmentSupport.UNSUPPORTED),
    restriction_notes=(REAL_VESSEL_INTERACTIVE_NOTE, ("wind", _REAL_WEATHER_NOTE), ("waves", _REAL_WEATHER_NOTE)),
    provides_ports=frozenset({Port.VESSEL_STATE}),
)

REAL_VESSEL_AUTOPILOT = AdapterSpec(
    id="real_vessel_autopilot",
    source=LayerRef.of(ControlLayerId.REAL_VESSEL),
    target=LayerRef.of(SimulationLayerId.REAL_VESSEL),
    description="Built in: the vessel's autopilot drives its own thrusters and rudder.",
    capabilities=REAL_VESSEL_CAPABILITIES,
    provides_ports=frozenset({Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE}),
    built_in=True,
)
