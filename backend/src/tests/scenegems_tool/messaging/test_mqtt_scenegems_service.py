"""The SceneGEMS service announces itself and takes no commands."""

from scenegems_tool.messaging.mqtt_scenegems_service import MqttSceneGEMSService
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline


def _service():
    return offline(MqttSceneGEMSService(CONNECTION, GEOFENCE))


def test_the_service_listens_on_its_command_topic_only():
    service = _service()
    assert service.listen_topics == [service.exec_command_topic]
    assert service.exec_command_topic == "waraps/service/virtual/real/scenegems_service/exec/command"


def test_commands_for_other_units_and_for_itself_are_accepted_without_effect():
    service = _service()
    deliver(service, service.exec_command_topic, {"execution-unit": "other"})
    deliver(service, service.exec_command_topic, {"execution-unit": "scenegems_service"})
    assert service.client.published == []


def test_heartbeat_sensor_info_and_direct_execution_info_are_published_with_no_tasks():
    service = _service()
    service.publish_heartbeat_and_sensor_info()
    published = {topic: message for topic, message in service.client.published}
    assert list(published) == [service.heartbeat_topic, service.sensor_info_topic, service.direct_execution_topic]
    heartbeat = published[service.heartbeat_topic]
    assert (heartbeat["type"], heartbeat["name"], heartbeat["agent-uuid"]) == ("HeartBeat", "scenegems_service", service.uuid)
    assert heartbeat["levels"] == ["sensor", "direct execution"] and heartbeat["rate"] == 1.0
    assert published[service.sensor_info_topic]["sensor-data-provided"] == []
    info = published[service.direct_execution_topic]
    assert (info["type"], info["tasks-available"], info["tasks-executing"]) == ("DirectExecutionInfo", [], [])
