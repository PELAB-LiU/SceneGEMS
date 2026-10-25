import pytest

from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.launchers.ca_certificate_mount import CaCertificateMount
from scenegems_tool.cluster.node.launchers.pooled.scene_generation_pool import SceneGenerationPool
from scenegems_tool.cluster.node.launchers.pooled.trajectory_generation_pool import TrajectoryGenerationPool


def test_a_volume_is_mounted_read_only_and_declared_external():
    compose = {"services": {"worker": {"environment": {"MQTT_CA_CERTIFICATE": "/somewhere/else.pem"}}}}
    CaCertificateMount("scenegems-node-m-n-trust").apply(compose, "worker")
    service = compose["services"]["worker"]
    assert service["volumes"] == ["scenegems-node-m-n-trust:/etc/scenegems/trust:ro"]
    assert service["environment"]["MQTT_CA_CERTIFICATE"] == "/etc/scenegems/trust/ca_certificate.pem"
    assert compose["volumes"] == {"scenegems-node-m-n-trust": {"external": True, "name": "scenegems-node-m-n-trust"}}


@pytest.mark.parametrize("folder", ["/var/lib/scenegems-node/trust", "C:/Users/node/state/trust"])
def test_a_host_folder_is_bind_mounted_without_a_volume_entry(folder):
    compose = {"services": {"worker": {"volumes": ["data:/data"]}}}
    mount = CaCertificateMount(folder)
    assert not mount.is_volume
    mount.apply(compose, "worker")
    assert compose["services"]["worker"]["volumes"] == ["data:/data", f"{folder}:/etc/scenegems/trust:ro"]
    assert "volumes" not in compose


def test_an_empty_source_is_refused():
    with pytest.raises(ValueError):
        CaCertificateMount("")


@pytest.mark.parametrize("pool_class, service_key", [(SceneGenerationPool, "scenario_generation"), (TrajectoryGenerationPool, "trajectory_generation")])
def test_scoped_pools_mount_the_ca_and_the_workbench_does_not(no_docker, mqtt_connection, geofence, pool_class, service_key):
    scope = InstanceScope.pooled("m1", "n1", service_key)
    pool = pool_class.for_scope(scope, mqtt_connection, geofence, workers=2, ca_certificate_mount=CaCertificateMount("trust-volume"))
    service = pool.build_compose()["services"][service_key]
    assert service["volumes"] == ["trust-volume:/etc/scenegems/trust:ro"]
    assert service["environment"]["MQTT_CA_CERTIFICATE"] == "/etc/scenegems/trust/ca_certificate.pem"
    workbench = pool_class.for_workbench(mqtt_connection, geofence).build_compose()["services"]
    assert all("volumes" not in service and "MQTT_CA_CERTIFICATE" not in service["environment"] for service in workbench.values())
