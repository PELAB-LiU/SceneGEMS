import type { ClientToServerMessage } from "../../../domain/simulation/wireTypes";
import { DEFAULT_MONITOR_NAME, defaultMonitorTopic } from "./monitorTopic";

/**
 * The live COLREGS monitor of the workbench's interactive simulation. It is not configured by
 * hand: once the MQTT broker is connected the workbench starts the server's own monitor
 * (scope internal) with the domain's COLREGS constants. Everything else is monitored by the
 * cluster's monitoring jobs.
 */

export function buildInitializeMonitorMessage(colregsConstraintsContent: string): ClientToServerMessage {
  return {
    type: "initialize_monitor",
    scope: "internal",
    name: DEFAULT_MONITOR_NAME,
    topic: defaultMonitorTopic(DEFAULT_MONITOR_NAME),
    colregsConstraintsContent,
  };
}

export function canInitializeMonitor(
  mqttBrokerStatus: "connected" | "disconnected",
  monitorStatus: "connected" | "disconnected",
  colregsConstraintsContent: string
): boolean {
  return mqttBrokerStatus === "connected" && monitorStatus !== "connected" && colregsConstraintsContent.trim().length > 0;
}
