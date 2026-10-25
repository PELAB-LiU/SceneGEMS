from scenegems_tool.cluster.node.launchers.container_environment import geofence_from_environment
from scenegems_tool.messaging.mqtt_client import mqtt_connection_from_environment
from scenegems_tool.subsystems.scenario_execution.scenario_execution_worker import ScenarioExecutionWorker


def main() -> None:
    mqtt_connection = mqtt_connection_from_environment()
    reference_geofence = geofence_from_environment()
    worker = ScenarioExecutionWorker.from_environment(mqtt_connection, reference_geofence)
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()
