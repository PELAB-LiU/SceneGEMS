/**
 * Playback state of an `EncounterView`, as a pure reducer so it is testable without a DOM.
 *
 * `cursor` is the continuous play head in scenario seconds; the shown frame is the last one
 * at or before it. While `following`, the cursor stays on the latest frame as live frames
 * arrive; seeking, stepping or playing ends following, and `followLive` resumes it.
 */

export const PLAYBACK_SPEEDS = [0.5, 1, 2, 5, 10, 30, 60] as const;
export const DEFAULT_PLAYBACK_SPEED = 5;

export interface EncounterPlaybackState {
  cursor: number;
  playing: boolean;
  speed: number;
  following: boolean;
}

/** The time range of the frames and whether more keep arriving. */
export interface PlaybackRange {
  start: number;
  end: number;
  live: boolean;
}

export type EncounterPlaybackAction =
  | ({ type: "range" } & PlaybackRange)
  | ({ type: "tick"; seconds: number } & PlaybackRange)
  | ({ type: "seek"; t: number } & PlaybackRange)
  | ({ type: "step"; direction: 1 | -1; step: number } & PlaybackRange)
  | ({ type: "togglePlay" } & PlaybackRange)
  | { type: "pause" }
  | { type: "speed"; speed: number }
  | ({ type: "followLive" } & PlaybackRange);

function clamp(t: number, range: PlaybackRange): number {
  return Math.min(Math.max(t, range.start), Math.max(range.start, range.end));
}

export function initialPlaybackState(
  range: PlaybackRange,
  initialTimestamp?: number
): EncounterPlaybackState {
  const hasInitial = initialTimestamp !== undefined;
  return {
    cursor: hasInitial ? clamp(initialTimestamp, range) : range.live ? range.end : range.start,
    playing: false,
    speed: DEFAULT_PLAYBACK_SPEED,
    following: range.live && !hasInitial,
  };
}

export function encounterPlaybackReducer(
  state: EncounterPlaybackState,
  action: EncounterPlaybackAction
): EncounterPlaybackState {
  switch (action.type) {
    case "range": {
      const following = state.following && action.live;
      const cursor = following ? action.end : clamp(state.cursor, action);
      if (cursor === state.cursor && following === state.following) {
        return state;
      }
      return { ...state, cursor, following };
    }
    case "tick": {
      if (!state.playing) {
        return state;
      }
      const next = state.cursor + state.speed * action.seconds;
      if (next >= action.end) {
        // Reaching the newest frame of a live run hands over to following it.
        return { ...state, cursor: action.end, playing: false, following: action.live };
      }
      return { ...state, cursor: clamp(next, action) };
    }
    case "seek":
      return { ...state, cursor: clamp(action.t, action), following: false };
    case "step":
      return {
        ...state,
        cursor: clamp(state.cursor + action.direction * action.step, action),
        playing: false,
        following: false,
      };
    case "togglePlay": {
      if (state.playing) {
        return { ...state, playing: false };
      }
      const atEnd = state.cursor >= action.end;
      if (atEnd && action.live) {
        return { ...state, following: true };
      }
      return {
        ...state,
        cursor: atEnd ? action.start : state.cursor,
        playing: action.end > action.start,
        following: false,
      };
    }
    case "pause":
      return state.playing ? { ...state, playing: false } : state;
    case "speed":
      return { ...state, speed: action.speed };
    case "followLive":
      return { ...state, cursor: action.end, playing: false, following: action.live };
  }
}

/** The last frame at or before `t` (the first frame before the start); frames sorted by timestamp. */
export function frameAtOrBefore<T extends { timestamp: number }>(frames: T[], t: number): T | null {
  if (frames.length === 0) {
    return null;
  }
  let lo = 0;
  let hi = frames.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (frames[mid]!.timestamp <= t) {
      lo = mid;
    } else {
      hi = mid - 1;
    }
  }
  return frames[lo]!;
}
