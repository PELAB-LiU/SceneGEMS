import { createContext, useContext } from "react";
import { useStore } from "zustand";
import { usePlaybackStore, type PlaybackState, type PlaybackStore } from "./playbackStore";

/**
 * The playback store of the workbench page that is shown. `WorkbenchSection` provides the page's
 * store; the canvas, the playback bar and the monitor panels read it here, so the scene page,
 * the trajectory page and the simulation page each render their own frames. Without a provider
 * it is the simulation page's store.
 */
export const PlaybackStoreContext = createContext<PlaybackStore>(usePlaybackStore);

/** The shown page's playback store, for `getState()` in handlers. */
export function useShownPlaybackStore(): PlaybackStore {
  return useContext(PlaybackStoreContext);
}

/** A selector over the shown page's playback store. */
export function useShownPlayback<T>(selector: (state: PlaybackState) => T): T {
  return useStore(useContext(PlaybackStoreContext), selector);
}
