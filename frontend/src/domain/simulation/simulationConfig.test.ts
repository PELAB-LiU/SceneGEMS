import { describe, expect, it } from "vitest";
import { gatewayWsUrl } from "./simulationConfig";

describe("workbench gateway URL", () => {
  it("follows the active cluster's operator URL", () => {
    expect(gatewayWsUrl("http://127.0.0.1:5174")).toBe("ws://127.0.0.1:5174/ws/scenegems_backend_service");
    expect(gatewayWsUrl("https://master.example/")).toBe("wss://master.example/ws/scenegems_backend_service");
  });

  it("falls back to the configured gateway without a cluster", () => {
    expect(gatewayWsUrl(null)).toMatch(/^wss?:\/\/.+\/ws\/scenegems_backend_service$/);
  });
});
