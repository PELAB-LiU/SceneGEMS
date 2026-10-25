import multiprocessing
import time

from scenegems_tool.cluster.node.launchers.container_environment import geofence_from_environment, worker_count_from_environment
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_scenario_generation_service import MqttScenarioGenerationService
from scenegems_tool.subsystems.scene_generation.scenario_generation_types import MAX_SCENE_GENERATION_WORKERS
from utils.file_system_utils import ensure_directories


def main() -> None:
    ensure_directories()
    mqtt_connection = MQttConnectionInfo.from_environment()
    reference_geofence = geofence_from_environment()
    service = MqttScenarioGenerationService(mqtt_connection, reference_geofence, worker_count_from_environment(MAX_SCENE_GENERATION_WORKERS))
    service.connect()
    service.start_runtime()
    tick_interval_sec = 1.0 / service.info_update_rate
    try:
        while True:
            time.sleep(tick_interval_sec)
            if service.is_connected:
                service.publish_heartbeat_and_sensor_info()
    except KeyboardInterrupt:
        service.stop_runtime()
        service.disconnect()


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    main()
