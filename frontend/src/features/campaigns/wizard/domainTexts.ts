import { DEFAULT_COLREGS_PRESET, DEFAULT_OBSTACLE_TYPES_PRESET, DEFAULT_VESSEL_TYPES_PRESET } from "../../workbench/controls/domainConfigPresets";

/**
 * The texts the domain step starts from: the workbench's current domain texts (kept per browser by
 * `usePersistedState` under `scenegems:colregs-text`, `vessel-types-text` and `obstacle-types-text`),
 * or the presets the workbench loads when it has none.
 */

export interface DomainTexts {
  colregsConstants: string;
  vesselTypes: string;
  obstacleTypes: string;
}

export const WORKBENCH_TEXT_KEYS = {
  colregsConstants: "scenegems:colregs-text",
  vesselTypes: "scenegems:vessel-types-text",
  obstacleTypes: "scenegems:obstacle-types-text",
} as const;

function readText(storage: Pick<Storage, "getItem"> | undefined, key: string): string {
  try {
    const raw = storage?.getItem(key);
    if (raw === null || raw === undefined) {
      return "";
    }
    const value: unknown = JSON.parse(raw);
    return typeof value === "string" ? value : "";
  } catch {
    return "";
  }
}

/** The workbench's domain texts; a text the workbench has not set (or that is blank) is empty. */
export function readWorkbenchDomainTexts(storage: Pick<Storage, "getItem"> | undefined = globalThis.localStorage): DomainTexts {
  return {
    colregsConstants: readText(storage, WORKBENCH_TEXT_KEYS.colregsConstants),
    vesselTypes: readText(storage, WORKBENCH_TEXT_KEYS.vesselTypes),
    obstacleTypes: readText(storage, WORKBENCH_TEXT_KEYS.obstacleTypes),
  };
}

async function fetchText(path: string, fetchImpl: typeof fetch): Promise<string> {
  const response = await fetchImpl(path);
  if (!response.ok) {
    throw new Error(`Could not load ${path} (${response.status})`);
  }
  return response.text();
}

/** The presets the workbench starts from, fetched from the app. */
export async function loadPresetDomainTexts(fetchImpl: typeof fetch = (input, init) => globalThis.fetch(input, init)): Promise<DomainTexts> {
  const [colregsConstants, vesselTypes, obstacleTypes] = await Promise.all([
    fetchText(DEFAULT_COLREGS_PRESET, fetchImpl),
    fetchText(DEFAULT_VESSEL_TYPES_PRESET, fetchImpl),
    fetchText(DEFAULT_OBSTACLE_TYPES_PRESET, fetchImpl),
  ]);
  return { colregsConstants, vesselTypes, obstacleTypes };
}

/**
 * The texts to start a customized domain from: the workbench's current texts, a preset for each one it
 * does not have. `source` says which of the two supplied most of them, for the note beside the editors.
 */
export async function startingDomainTexts(
  storage?: Pick<Storage, "getItem">,
  fetchImpl?: typeof fetch
): Promise<{ texts: DomainTexts; fromWorkbench: (keyof DomainTexts)[] }> {
  const workbench = readWorkbenchDomainTexts(storage);
  const fromWorkbench = (Object.keys(workbench) as (keyof DomainTexts)[]).filter((key) => workbench[key].trim().length > 0);
  if (fromWorkbench.length === 3) {
    return { texts: workbench, fromWorkbench };
  }
  const presets = await loadPresetDomainTexts(fetchImpl);
  return {
    texts: {
      colregsConstants: workbench.colregsConstants.trim() ? workbench.colregsConstants : presets.colregsConstants,
      vesselTypes: workbench.vesselTypes.trim() ? workbench.vesselTypes : presets.vesselTypes,
      obstacleTypes: workbench.obstacleTypes.trim() ? workbench.obstacleTypes : presets.obstacleTypes,
    },
    fromWorkbench,
  };
}
