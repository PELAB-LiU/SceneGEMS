import { useEffect, useMemo, useReducer, useRef } from "react";
import type { SimulationFrame } from "../../domain/simulation/types";
import {
  encounterPlaybackReducer,
  frameAtOrBefore,
  initialPlaybackState,
  type PlaybackRange,
} from "./encounterPlayback";

interface Options {
  live: boolean;
  initialTimestamp?: number;
  timeStep?: number | null;
}

/**
 * Local playback over `frames` (sorted by timestamp): the play head, play and pause driven
 * by animation frames, speed, and following the latest frame while live.
 */
export function useEncounterPlayback(frames: SimulationFrame[], { live, initialTimestamp, timeStep }: Options) {
  const start = frames[0]?.timestamp ?? 0;
  const end = frames[frames.length - 1]?.timestamp ?? 0;
  const range: PlaybackRange = useMemo(() => ({ start, end, live }), [start, end, live]);
  const [state, dispatch] = useReducer(encounterPlaybackReducer, range, (r) =>
    initialPlaybackState(r, initialTimestamp)
  );

  useEffect(() => {
    dispatch({ type: "range", ...range });
  }, [range]);

  const rangeRef = useRef(range);
  useEffect(() => {
    rangeRef.current = range;
  }, [range]);

  useEffect(() => {
    if (!state.playing) {
      return;
    }
    let last: number | null = null;
    let handle = 0;
    const loop = (now: number) => {
      if (last !== null) {
        dispatch({ type: "tick", seconds: (now - last) / 1000, ...rangeRef.current });
      }
      last = now;
      handle = requestAnimationFrame(loop);
    };
    handle = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(handle);
  }, [state.playing]);

  const frame = useMemo(() => frameAtOrBefore(frames, state.cursor), [frames, state.cursor]);

  const step = timeStep ?? frame?.timeStep ?? 1;
  const actions = useMemo(
    () => ({
      togglePlay: () => dispatch({ type: "togglePlay", ...rangeRef.current }),
      seek: (t: number) => dispatch({ type: "seek", t, ...rangeRef.current }),
      step: (direction: 1 | -1) => dispatch({ type: "step", direction, step, ...rangeRef.current }),
      setSpeed: (speed: number) => dispatch({ type: "speed", speed }),
      followLive: () => dispatch({ type: "followLive", ...rangeRef.current }),
    }),
    [step]
  );

  return { state, frame, range, actions };
}
