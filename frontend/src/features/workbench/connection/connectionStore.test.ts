import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { ConnectionPersisted } from "./connectionStore";
import { local_mqtt_connection } from "./connectionLibrary";
import { MemoryStorage } from "../../../test/memoryStorage";

type ConnectionModule = typeof import("./connectionStore");

const storage = new MemoryStorage();
let connection: ConnectionModule;

beforeAll(async () => {
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", { localStorage: storage });
  connection = await import("./connectionStore");
});

afterAll(() => {
  vi.unstubAllGlobals();
});

function migrate(persisted: unknown, version: number) {
  const run = connection.useConnectionStore.persist.getOptions().migrate;
  if (!run) {
    throw new Error("connection store has no migrate");
  }
  return run(persisted, version) as ConnectionPersisted;
}

describe("connection form migration", () => {
  it("refreshes an explicitly selected local preset to the current local broker", () => {
    const migrated = migrate(
      {
        user: "kept",
        password: "secret",
        agentBroker: "127.0.0.1",
        clientBroker: "127.0.0.1",
        port: 1884,
        tlsConnection: true,
        allowCertificates: true,
        selectedPreset: "local_mqtt_connection",
      },
      1
    );
    expect(migrated.agentBroker).toBe(local_mqtt_connection.agent_broker);
    expect(migrated.clientBroker).toBe(local_mqtt_connection.client_broker);
    expect(migrated.port).toBe(local_mqtt_connection.port);
    expect(migrated.tlsConnection).toBe(local_mqtt_connection.tls_connection);
    expect(migrated.user).toBe("kept");
    expect(migrated.password).toBe("secret");
    expect(migrated).not.toHaveProperty("state");
  });

  it("leaves a hand-typed or other preset address in place", () => {
    const handTyped = {
      agentBroker: "10.0.0.8",
      clientBroker: "10.0.0.8",
      port: 1883,
      tlsConnection: false,
      selectedPreset: "" as const,
    };
    expect(migrate(handTyped, 1)).toBe(handTyped);

    const host = {
      agentBroker: "localhost",
      clientBroker: "localhost",
      port: 1882,
      tlsConnection: false,
      selectedPreset: "host_mqtt_connection" as const,
    };
    expect(migrate(host, 0)).toBe(host);
  });

  it("does not refresh a local preset that is already on the current version", () => {
    const current = {
      agentBroker: "custom-broker",
      clientBroker: "custom-broker",
      port: 1885,
      tlsConnection: true,
      selectedPreset: "local_mqtt_connection" as const,
    };
    expect(migrate(current, 2)).toBe(current);
  });
});
