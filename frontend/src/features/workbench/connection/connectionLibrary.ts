export interface MqttConnectionInfo {
  user: string;
  password: string;
  agent_broker: string;
  client_broker: string;
  port: number;
  tls_connection: boolean;
  allow_certificates?: boolean;
}

/**
 * The broker profiles of the Connections page. The master's own broker is the default: the
 * server knows its address (`mqtt_broker_status.masterBroker`), so the form sends
 * `use_master_broker` instead of an address. Any other broker is an external one.
 */
export type MqttConnectionPresetKey = "master_broker" | "waraps_tls_broker";

export const MASTER_BROKER_PRESET = "master_broker" satisfies MqttConnectionPresetKey;

/** The public broker of broker.waraps.org, over TLS, where real vessels and external agents meet. */
export const waraps_tls_broker: MqttConnectionInfo = {
  user: "mqtt",
  password: "",
  agent_broker: "broker.waraps.org",
  client_broker: "broker.waraps.org",
  port: 8883,
  tls_connection: true,
};

/** The fields a profile fills in; the master broker has none of its own. */
export const mqttConnectionLibrary: Record<Exclude<MqttConnectionPresetKey, "master_broker">, MqttConnectionInfo> = {
  waraps_tls_broker,
};

export const PRESET_LABELS: Record<MqttConnectionPresetKey | "", string> = {
  master_broker: "Master broker (default)",
  waraps_tls_broker: "broker.waraps.org over TLS",
  "": "Other broker",
};
