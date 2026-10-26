import { describe, expect, it, vi } from "vitest";
import { MemoryStorage } from "../../../test/memoryStorage";
import { loadPresetDomainTexts, readWorkbenchDomainTexts, startingDomainTexts, WORKBENCH_TEXT_KEYS } from "./domainTexts";

function storageWith(values: Partial<Record<keyof typeof WORKBENCH_TEXT_KEYS, string>>): MemoryStorage {
  const storage = new MemoryStorage();
  for (const [name, text] of Object.entries(values)) {
    storage.setItem(WORKBENCH_TEXT_KEYS[name as keyof typeof WORKBENCH_TEXT_KEYS], JSON.stringify(text));
  }
  return storage;
}

const presetFetch = vi.fn(async (path: string) => new Response(`# preset ${path}\nA: 1\n`, { status: 200 }));

describe("workbench domain texts", () => {
  it("reads the texts the workbench persisted as JSON strings", () => {
    const storage = storageWith({ colregsConstants: "A: 1\n", vesselTypes: "V:\n  length: 3\n" });
    expect(readWorkbenchDomainTexts(storage)).toEqual({ colregsConstants: "A: 1\n", vesselTypes: "V:\n  length: 3\n", obstacleTypes: "" });
  });

  it("treats a missing, broken or non-string value as empty", () => {
    const storage = new MemoryStorage();
    storage.setItem(WORKBENCH_TEXT_KEYS.colregsConstants, "{not json");
    storage.setItem(WORKBENCH_TEXT_KEYS.vesselTypes, "42");
    expect(readWorkbenchDomainTexts(storage)).toEqual({ colregsConstants: "", vesselTypes: "", obstacleTypes: "" });
  });
});

describe("starting domain texts", () => {
  it("uses the workbench's texts without fetching when it has all three", async () => {
    presetFetch.mockClear();
    const storage = storageWith({ colregsConstants: "A: 1\n", vesselTypes: "V: 1\n", obstacleTypes: "O: 1\n" });
    const result = await startingDomainTexts(storage, presetFetch as unknown as typeof fetch);
    expect(result.texts).toEqual({ colregsConstants: "A: 1\n", vesselTypes: "V: 1\n", obstacleTypes: "O: 1\n" });
    expect(result.fromWorkbench).toEqual(["colregsConstants", "vesselTypes", "obstacleTypes"]);
    expect(presetFetch).not.toHaveBeenCalled();
  });

  it("fills what the workbench lacks from the presets", async () => {
    presetFetch.mockClear();
    const storage = storageWith({ colregsConstants: "A: 2\n", vesselTypes: "   " });
    const result = await startingDomainTexts(storage, presetFetch as unknown as typeof fetch);
    expect(result.texts.colregsConstants).toBe("A: 2\n");
    expect(result.texts.vesselTypes).toContain("# preset /domain_config/vessel_types/vessel_types.yaml");
    expect(result.texts.obstacleTypes).toContain("static_obstacle_types.yaml");
    expect(result.fromWorkbench).toEqual(["colregsConstants"]);
  });

  it("fails with the path when a preset does not load", async () => {
    const failing = vi.fn(async () => new Response("no", { status: 404 }));
    await expect(loadPresetDomainTexts(failing as unknown as typeof fetch)).rejects.toThrow(/\/domain_config\/.* \(404\)/);
  });
});
