import { expect, it } from "vitest";
import { monitorSectionKey } from "./monitorSectionKey";

it("builds a stream scoped key", () => {
  expect(monitorSectionKey("live" as never, "layers")).toBe("monitor:live:layers");
});
