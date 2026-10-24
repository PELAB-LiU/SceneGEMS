"""Specs of the replay ASV software and the adapters it drives a control layer through."""

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, LayerRef

REPLAY_LAYER = LayerSpec(
    layer=LayerRef.of(AsvSoftwareId.REPLAY),
    description="Follows the generated trajectory of the vessel (the workbench's autonomous control mode).",
)

REPLAY_STATE_FOLLOWER = AdapterSpec(
    id="replay_state_follower",
    source=LayerRef.of(AsvSoftwareId.REPLAY),
    target=LayerRef.of(ControlLayerId.NONE),
    description="Direct state follower in pure Python: heading and speed commands that track the trajectory, stepped only by the simulation clock.",
    provides_ports=frozenset({Port.HEADING_SPEED_CMD}),
    requires_ports=frozenset({Port.VESSEL_STATE, Port.CLOCK}),
)

REPLAY_ARDUAGENT_FOLLOWER = AdapterSpec(
    id="replay_arduagent_follower",
    source=LayerRef.of(AsvSoftwareId.REPLAY),
    target=LayerRef.of(ControlLayerId.ARDUPILOT),
    description="ArduAgent waypoint follower over MAVLink: the thinned trajectory is uploaded as an AUTO mission over WARA-PS MQTT and ArduPilot flies it in simulated time.",
    # ArduAgent runs on the wall clock (main loop 0.2 s, positions at 2 Hz), so it is not
    # stepped by the simulation clock. Its timing effect is part of the measured bounds of
    # the control and simulation pair.
    capabilities=Capabilities(lockstep=False),
    provides_ports=frozenset({Port.WAYPOINT_MISSION, Port.MAVLINK}),
    requires_ports=frozenset({Port.VESSEL_STATE}),
)
