/**
 * The one place the Observe viewers get their encounter view from. P5.8 builds
 * `features/encounter/EncounterView.tsx` with the props below (design doc 5.3, "Wave 2
 * contracts"); until it is merged this is a stand-in with the same props. The wave 2 merge
 * replaces this file's two exports with
 * `export { EncounterView, type EncounterViewProps } from "../encounter/EncounterView";`
 * and deletes `EncounterViewStandIn.tsx`.
 */
import type { SimulationFrame } from "../../domain/simulation/types";

export interface EncounterViewProps {
  /** Frames in the workbench's frame wire format, as `domain/simulation/protocol.ts` parses them. */
  frames: SimulationFrame[];
  /** Seconds between frames, when known. */
  timeStep?: number | null;
  /** Frames keep arriving: follow the latest until the user scrubs. */
  live?: boolean;
  title?: string;
  initialTimestamp?: number;
  onTimestampChange?: (timestamp: number) => void;
}

export { EncounterViewStandIn as EncounterView } from "./EncounterViewStandIn";
