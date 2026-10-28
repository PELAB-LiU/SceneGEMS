import type { TrajectoryStream } from "../../../app/uiStore";
import { useStore } from "zustand";
import { useShownPlaybackStore } from "../../../domain/playback/playbackContext";
import { getCurrentFrame, getCurrentSimulationFrame } from "../../../domain/playback/playbackStore";
import type { SimulationFrame } from "../../../domain/simulation/types";

/** Frame for a specific trajectory stream (animation vs simulation playback buffer) of the shown page. */
export function useMonitorFrameForKind(panelKind: TrajectoryStream): {
  frame: SimulationFrame | null;
  panelKind: TrajectoryStream;
} {
  const playback = useStore(useShownPlaybackStore());
  if (panelKind === "animation") {
    return { frame: getCurrentFrame(playback), panelKind: "animation" };
  }
  return { frame: getCurrentSimulationFrame(playback), panelKind: "simulation" };
}
