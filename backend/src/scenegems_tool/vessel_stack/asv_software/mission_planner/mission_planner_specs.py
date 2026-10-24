"""Specs of the mission_planner ASV software: an operator or external software on a MAVLink port.

Phase 1 maps the workbench's external control mode here: ArduAgent sends the vessel toward
the last waypoint of its trajectory, and whoever is connected to the MAVLink port that
MAVProxy exposes can take over. The dedicated interactive adapter is Phase 2.
"""

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, LayerRef

MISSION_PLANNER_LAYER = LayerSpec(
    layer=LayerRef.of(AsvSoftwareId.MISSION_PLANNER),
    description="A human operator or external software on a MAVLink endpoint (the workbench's external control mode).",
    # A person in the loop is neither stepped by the simulation clock nor repeatable. The
    # pace stays the operator's choice, so it does not cap the speedup.
    capabilities=Capabilities(lockstep=False, repeatability_tier=RepeatabilityTier.NONE, interactive_only=True),
    restriction_notes=(("interactive_only", "a person drives the vessel, so it is not used in unattended campaigns"),),
    requires_ports=frozenset({Port.MAVLINK}),
)

MISSION_PLANNER_MAVLINK_PORT = AdapterSpec(
    id="mission_planner_mavlink_port",
    source=LayerRef.of(AsvSoftwareId.MISSION_PLANNER),
    target=LayerRef.of(ControlLayerId.ARDUPILOT),
    description="Exposed MAVLink port: MAVProxy forwards each vessel to a UDP ground control station port, and ArduAgent sends the vessel toward its last waypoint.",
    capabilities=Capabilities(lockstep=False),
    provides_ports=frozenset({Port.MAVLINK}),
)
