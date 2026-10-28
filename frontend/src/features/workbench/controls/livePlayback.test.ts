import { describe, expect, it, vi } from "vitest";
import { activateLiveMode, getLatestSimulationTimestamp } from "./livePlayback";

describe("handleLivePlayback", () => {

  it("activates live follow via store action", () => {
    const followSimulationLive = vi.fn();

    activateLiveMode({ followSimulationLive });

    expect(followSimulationLive).toHaveBeenCalledTimes(1);
  });

  it("returns the latest buffered simulation timestamp", () => {
    expect(
      getLatestSimulationTimestamp([
        { timestamp: 5 },
        { timestamp: 8 },
        { timestamp: 13 },
      ])
    ).toBe(13);
  });

  it("returns null for an empty simulation frame list", () => {
    expect(getLatestSimulationTimestamp([])).toBeNull();
  });
});
