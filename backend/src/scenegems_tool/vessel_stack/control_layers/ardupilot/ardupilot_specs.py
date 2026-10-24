"""Specs of the ArduPilot control layer: per vessel SITL, MAVProxy and ArduAgent."""

from scenegems_tool.vessel_stack.contracts.adapter_spec import ContainerSpec, LayerSpec
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, LayerRef
from utils.file_system_utils import SITL_ENTRYPOINT_CONTAINER_PATH

SITL_CONTAINER = ContainerSpec(
    image="${SITL_IMAGE:-scenegems-ardupilot-sitl:latest}",
    build_fingerprint_source="deploy/images/sitl",
    entrypoint=SITL_ENTRYPOINT_CONTAINER_PATH,
)
MAVPROXY_CONTAINER = ContainerSpec(
    image="${MAVPROXY_IMAGE:-scenegems-mavproxy:latest}",
    build_fingerprint_source="deploy/images/mavproxy",
    entrypoint="python3 -m MAVProxy.mavproxy",
)
ARDUAGENT_CONTAINER = ContainerSpec(
    image="${ARDUAGENT_IMAGE:-scenegems-arduagent:latest}",
    build_fingerprint_source="deploy/images/arduagent",
    entrypoint="python -B -u /app/main.py",
)

ARDUPILOT_CONTROL_LAYER = LayerSpec(
    layer=LayerRef.of(ControlLayerId.ARDUPILOT),
    description="ArduPilot Rover SITL as the low-level controller. Every vessel gets SITL with a generated parameter file, MAVProxy and ArduAgent.",
    provides_ports=frozenset({Port.MAVLINK, Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.MAVLINK, Port.WAYPOINT_MISSION, Port.ENVIRONMENT}),
    # ArduAgent is generated with SITL and MAVProxy in one per-vessel service set today,
    # so its container is listed here rather than on the ASV-side adapters.
    containers=(SITL_CONTAINER, MAVPROXY_CONTAINER, ARDUAGENT_CONTAINER),
)
