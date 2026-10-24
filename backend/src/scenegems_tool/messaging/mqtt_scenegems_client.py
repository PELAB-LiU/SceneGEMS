from typing import List

from scenegems_tool.messaging.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence


class MqttSceneGEMSClient(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo, topic: str, reference_geofence: Geofence):
        super().__init__(name="scenegems_client", topic=topic, mqtt_connection=mqtt_connection, reference_geofence=reference_geofence)

    @property
    def listen_topics(self) -> List[str]:
        return [
            self.exec_feedback_topic,
            self.exec_response_topic,
        ]

    def _on_message(self, msg, payload):
        pass
