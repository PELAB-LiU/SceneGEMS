"""Compose content of the pooled services: the workbench's is unchanged by instance scoping, a node's is scoped."""

from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.launchers.compose_project import dump_compose
from scenegems_tool.cluster.node.launchers.pooled.monitor_service import MonitorService
from scenegems_tool.cluster.node.launchers.pooled.scene_generation_pool import SceneGenerationPool
from scenegems_tool.cluster.node.launchers.pooled.trajectory_generation_pool import TrajectoryGenerationPool
from utils.file_system_utils import MONITORING_GEN_FOLDER, RUNTIME_ASSETS_VOLUME

WORKBENCH_ENVIRONMENT = {
    "MQTT_USER": "user",
    "MQTT_PASSWORD": "secret",
    "MQTT_BROKER": "broker",
    "MQTT_PORT": "1883",
    "MQTT_TLS": "0",
    "MQTT_ALLOW_CERTIFICATES": "0",
    "GEOFENCE_LATITUDE": "57.7",
    "GEOFENCE_LONGITUDE": "11.9",
    "GEOFENCE_RADIUS": "2000.0",
}


def workbench_pool_compose(service: str, image: str, cpus: int) -> dict:
    """The compose file the workbench wrote before the launchers moved to cluster/node (same keys, same order)."""
    return {
        "services": {
            service: {
                "image": image,
                "container_name": service,
                "hostname": service,
                "environment": dict(WORKBENCH_ENVIRONMENT),
                "cpus": cpus,
                "networks": [f"{service}_net", "scenegems_broker"],
            }
        },
        "networks": {
            f"{service}_net": {"name": f"{service}_net", "driver": "bridge"},
            "scenegems_broker": {"external": True, "name": "scenegems_default"},
        },
        "volumes": {RUNTIME_ASSETS_VOLUME: {"external": True}},
    }


def test_scoped_pool_is_sized_by_slots_and_named_by_scope(no_docker, mqtt_connection, geofence):
    scope = InstanceScope.pooled("m1", "n1", "scene_generation")
    pool = SceneGenerationPool.for_scope(scope, mqtt_connection, geofence, workers=3, broker_network="node_broker_net")
    compose = pool.build_compose()
    service = compose["services"]["scene_generation"]
    assert service["container_name"] == service["hostname"] == "scenegems-m1-n1-scene_generation-0"
    assert service["cpus"] == 4
    assert service["environment"]["WORKER_COUNT"] == "3"
    assert service["environment"]["MQTT_TOPIC_PREFIX"] == "scenegems/m1/n1/scene_generation-0/"
    assert compose["networks"]["scene_generation_net"]["name"] == "scenegems-m1-n1-scene_generation-0-net"
    assert compose["networks"]["scenegems_broker"] == {"external": True, "name": "node_broker_net"}
    assert pool.project.name == scope.compose_project
    assert pool.compose_filename == f"{scope.folder}/docker-compose.yml"
    # Clients of the pool use the same prefix as the container.
    assert pool.mqtt_connection.topic_prefix == scope.topic_prefix
    assert mqtt_connection.topic_prefix == ""


def test_two_scoped_pools_share_no_docker_name(no_docker, mqtt_connection, geofence):
    first = TrajectoryGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "trajectory_generation"), mqtt_connection, geofence, workers=1)
    second = TrajectoryGenerationPool.for_scope(InstanceScope.pooled("m1", "n2", "trajectory_generation"), mqtt_connection, geofence, workers=1)

    def names(pool):
        compose = pool.build_compose()
        service = compose["services"]["trajectory_generation"]
        return {pool.project.name, service["container_name"], compose["networks"]["trajectory_generation_net"]["name"], pool.compose_filename, pool.mqtt_connection.topic_prefix}

    assert not names(first) & names(second)


def test_image_override_applies_to_pools(no_docker, monkeypatch, mqtt_connection, geofence):
    monkeypatch.setenv("SCENE_GENERATION_IMAGE", "scenegems-scene-generation-subsystem:branch")
    pool = SceneGenerationPool.for_scope(InstanceScope.pooled("m1", "n1", "scene_generation"), mqtt_connection, geofence, workers=1, broker_network="node_broker_net")
    assert pool.build_compose()["services"]["scene_generation"]["image"] == "scenegems-scene-generation-subsystem:branch"


def test_workbench_monitor_compose_is_unchanged(no_docker, mqtt_connection, geofence):
    monitor = MonitorService.for_workbench(mqtt_connection, geofence, "scenario monitor", "waraps/service/virtual/real/scenario_monitor", "rules: []\n")
    instance_id = monitor.names.compose_project.rsplit("-", 1)[1]
    assert monitor.names.compose_project == f"scenegems-monitoring-subsystem-{instance_id}"
    assert monitor.container_name == f"scenario_monitor-{instance_id}"
    assert monitor.compose_filename == f"{MONITORING_GEN_FOLDER}/{instance_id}/docker-compose.yml"
    expected = {
        "services": {
            "monitoring": {
                "image": "scenegems-monitoring-subsystem:latest",
                "container_name": monitor.container_name,
                "hostname": monitor.container_name,
                "environment": {
                    **WORKBENCH_ENVIRONMENT,
                    "MONITOR_AGENT_NAME": "scenario monitor",
                    "MONITOR_TOPIC": "waraps/service/virtual/real/scenario_monitor",
                    "COLREGS_CONSTRAINTS_YAML_B64": "cnVsZXM6IFtdCg==",
                    "PYTHONUNBUFFERED": "1",
                },
                "cpus": 1,
                "networks": ["scenegems_broker"],
            }
        },
        "networks": {"scenegems_broker": {"external": True, "name": "scenegems_default"}},
    }
    assert dump_compose(monitor.build_compose()) == dump_compose(expected)


def test_scoped_monitor_is_named_by_scope(no_docker, mqtt_connection, geofence):
    scope = InstanceScope.pooled("m1", "n1", "monitoring")
    monitor = MonitorService.for_scope(scope, mqtt_connection, geofence, "scenario_monitor", "waraps/service/virtual/real/scenario_monitor", "rules: []\n")
    service = monitor.build_compose()["services"]["monitoring"]
    assert service["container_name"] == "scenegems-m1-n1-monitoring-0"
    assert service["environment"]["MQTT_TOPIC_PREFIX"] == "scenegems/m1/n1/monitoring-0/"
    assert monitor.names.scoped
