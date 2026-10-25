from scenegems_tool.cluster.node.daemon import node_runtime
from scenegems_tool.cluster.node.daemon.configuration.node_configuration import NodeConfiguration
from scenegems_tool.cluster.node.daemon.node_runtime import broker_connection, build_node_context, instance_prefix, remove_leftover_instances
from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.launchers.ca_certificate_mount import CaCertificateMount
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.pairing import BrokerAccess, PairingResponse
from scenegems_tool.messaging.mqtt_client import mqtt_container_environment

RESPONSE = PairingResponse(
    master_id="lab-master",
    node_id="worker-1-abc123",
    node_credential="worker-1-abc123.secret",
    ca_certificate_pem="-----BEGIN CERTIFICATE-----\nAA==\n-----END CERTIFICATE-----\n",
    broker=BrokerAccess(host="192.168.1.10", port=8883, username="worker-1-abc123", password="broker-secret", topic_scope="scenegems/lab-master/worker-1-abc123"),
)


def configuration(tmp_path, **changes) -> NodeConfiguration:
    values = {
        "SCENEGEMS_MASTER_URL": "https://192.168.1.10:8443",
        "SCENEGEMS_MASTER_ID": "lab-master",
        "SCENEGEMS_MASTER_CA_SHA256": "a" * 64,
        "SCENEGEMS_NODE_NAME": "worker-1",
        "SCENEGEMS_NODE_CAPABILITIES": "scene_generation:3,simulation.kinematic:2",
        "SCENEGEMS_NODE_STATE_DIR": str(tmp_path / "state"),
        "SCENEGEMS_NODE_TRUST_SOURCE": "scenegems-node-lab-master-worker-1-trust",
        "SCENEGEMS_DOCKER_NETWORK": "scenegems-node-lab-master-worker-1",
        "SCENEGEMS_NODE_REFERENCE_GEOFENCE": "57.7,11.9,2000",
    }
    values.update(changes)
    return NodeConfiguration.from_values(values)


def test_the_broker_is_the_central_one_over_tls_with_the_node_account():
    connection = broker_connection(RESPONSE, "/state/ca_certificate.pem")
    assert (connection.user, connection.password) == ("worker-1-abc123", "broker-secret")
    assert connection.client_broker == connection.agent_broker == "192.168.1.10" and connection.port == 8883
    assert connection.tls_connection and not connection.allow_certificates
    assert connection.ca_certificate_path == "/state/ca_certificate.pem"
    assert connection.topic_prefix == ""  # every instance adds its own


def test_the_node_context_carries_ids_slots_network_and_the_ca_mount(tmp_path):
    node = build_node_context(configuration(tmp_path), RESPONSE)
    assert (node.master_id, node.node_id) == ("lab-master", "worker-1-abc123")
    assert node.slots == {JobType.SCENE_GENERATION: 3, JobType.SIMULATION_KINEMATIC: 2}
    assert node.pool_workers(Subsystem.SCENE_GENERATION) == 3
    assert node.broker_network == "scenegems-node-lab-master-worker-1"
    assert node.ca_certificate_mount == CaCertificateMount("scenegems-node-lab-master-worker-1-trust")
    assert node.mqtt_connection.ca_certificate_path == str(tmp_path / "state" / "ca_certificate.pem")
    assert (node.reference_geofence.latitude, node.reference_geofence.radius_meters) == (57.7, 2000.0)
    # Pool instances live under the node's own topic scope, the one its broker account may use.
    assert node.pools.scope(Subsystem.SCENE_GENERATION).topic_prefix.startswith(f"{RESPONSE.broker.topic_scope}/")


def test_the_node_context_moves_artifacts_over_the_node_api_with_a_cache_in_the_state_folder(tmp_path):
    node = build_node_context(configuration(tmp_path, SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES="1000"), RESPONSE)
    assert node.artifacts.client.master_url == "https://192.168.1.10:8443"
    assert node.artifacts.cache.folder == tmp_path / "state" / "artifacts" and node.artifacts.cache.max_bytes == 1000
    assert build_node_context(configuration(tmp_path, SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES="0"), RESPONSE).artifacts.cache is None


def test_pool_containers_get_the_ca_path_inside_the_container(tmp_path, monkeypatch):
    from scenegems_tool.cluster.node.launchers.pooled.pooled_service import PooledService

    monkeypatch.setattr(PooledService, "_run_container_lifecycle_startup", lambda self, compose: None)
    node = build_node_context(configuration(tmp_path), RESPONSE)
    pool = node.pools.get(Subsystem.SCENE_GENERATION)
    compose = pool.build_compose()
    service = compose["services"]["scenario_generation"]
    assert service["environment"]["MQTT_CA_CERTIFICATE"] == "/etc/scenegems/trust/ca_certificate.pem"
    assert service["environment"]["MQTT_TLS"] == "1" and service["environment"]["MQTT_USER"] == "worker-1-abc123"
    assert service["volumes"] == ["scenegems-node-lab-master-worker-1-trust:/etc/scenegems/trust:ro"]
    assert compose["volumes"]["scenegems-node-lab-master-worker-1-trust"] == {"external": True, "name": "scenegems-node-lab-master-worker-1-trust"}
    # This process keeps its own path to the same file.
    assert mqtt_container_environment(node.mqtt_connection)["MQTT_CA_CERTIFICATE"] == str(tmp_path / "state" / "ca_certificate.pem")
    node.shutdown()


def test_leftover_instances_of_this_node_are_removed(tmp_path, monkeypatch):
    removed = []

    class RecordingProject:
        def __init__(self, name, compose_filename):
            self.name = name

        def force_remove(self, networks=False):
            removed.append((self.name, networks))

    monkeypatch.setattr(node_runtime, "ComposeProject", RecordingProject)
    instances = tmp_path / "instances"
    mine = InstanceScope.per_job("lab-master", "worker-1-abc123", "job-7-1").docker_name
    pool = InstanceScope.pooled("lab-master", "worker-1-abc123", "scene_generation").docker_name
    other_node = InstanceScope.per_job("lab-master", "worker-2-def456", "job-8-1").docker_name
    for name in (mine, pool, other_node):
        (instances / name).mkdir(parents=True)

    assert remove_leftover_instances("lab-master", "worker-1-abc123", str(instances)) == sorted([mine, pool])
    assert sorted(removed) == sorted([(mine, True), (pool, True)])
    assert [folder.name for folder in instances.iterdir()] == [other_node]
    assert remove_leftover_instances("lab-master", "worker-1-abc123", str(tmp_path / "missing")) == []
    assert instance_prefix("lab-master", "worker-1-abc123") == "scenegems-lab-master-worker-1-abc123-"
