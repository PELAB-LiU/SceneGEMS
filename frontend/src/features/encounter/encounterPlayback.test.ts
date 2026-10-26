import { describe, expect, it } from "vitest";
import {
  DEFAULT_PLAYBACK_SPEED,
  encounterPlaybackReducer as reduce,
  frameAtOrBefore,
  initialPlaybackState,
  type PlaybackRange,
} from "./encounterPlayback";

const recorded: PlaybackRange = { start: 0, end: 720, live: false };
const live: PlaybackRange = { start: 0, end: 120, live: true };

describe("initial state", () => {
  it("starts a recorded run at its start, paused", () => {
    expect(initialPlaybackState(recorded)).toEqual({
      cursor: 0,
      playing: false,
      speed: DEFAULT_PLAYBACK_SPEED,
      following: false,
    });
  });

  it("starts a live run on its latest frame, following", () => {
    const state = initialPlaybackState(live);
    expect(state.cursor).toBe(120);
    expect(state.following).toBe(true);
  });

  it("honours an initial timestamp, clamped to the frames", () => {
    expect(initialPlaybackState(recorded, 300).cursor).toBe(300);
    expect(initialPlaybackState(recorded, 9999).cursor).toBe(720);
    expect(initialPlaybackState(live, 40)).toMatchObject({ cursor: 40, following: false });
  });
});

describe("following a live run", () => {
  it("moves to each new latest frame while following", () => {
    let state = initialPlaybackState(live);
    state = reduce(state, { type: "range", start: 0, end: 130, live: true });
    expect(state.cursor).toBe(130);
    state = reduce(state, { type: "range", start: 0, end: 140, live: true });
    expect(state.cursor).toBe(140);
  });

  it("stops following when the user scrubs, and stays put as frames arrive", () => {
    let state = initialPlaybackState(live);
    state = reduce(state, { type: "seek", t: 60, ...live });
    expect(state).toMatchObject({ cursor: 60, following: false });
    state = reduce(state, { type: "range", start: 0, end: 200, live: true });
    expect(state.cursor).toBe(60);
  });

  it("resumes following on request", () => {
    let state = reduce(initialPlaybackState(live), { type: "seek", t: 10, ...live });
    state = reduce(state, { type: "followLive", start: 0, end: 150, live: true });
    expect(state).toMatchObject({ cursor: 150, following: true, playing: false });
  });

  it("hands over to following when playback catches up with the newest frame", () => {
    let state = reduce(initialPlaybackState(live), { type: "seek", t: 100, ...live });
    state = reduce(state, { type: "togglePlay", ...live });
    state = reduce(state, { type: "tick", seconds: 10, ...live });
    expect(state).toMatchObject({ cursor: 120, playing: false, following: true });
  });

  it("ends following when the run stops being live", () => {
    let state = initialPlaybackState(live);
    state = reduce(state, { type: "range", start: 0, end: 150, live: false });
    expect(state).toMatchObject({ cursor: 120, following: false });
  });
});

describe("playing a recorded run", () => {
  it("advances by speed times elapsed time", () => {
    let state = reduce(initialPlaybackState(recorded), { type: "speed", speed: 10 });
    state = reduce(state, { type: "togglePlay", ...recorded });
    expect(state.playing).toBe(true);
    state = reduce(state, { type: "tick", seconds: 0.5, ...recorded });
    expect(state.cursor).toBeCloseTo(5);
    state = reduce(state, { type: "speed", speed: 60 });
    state = reduce(state, { type: "tick", seconds: 1, ...recorded });
    expect(state.cursor).toBeCloseTo(65);
  });

  it("ignores ticks while paused", () => {
    const state = initialPlaybackState(recorded);
    expect(reduce(state, { type: "tick", seconds: 5, ...recorded })).toBe(state);
  });

  it("stops at the end and restarts from the start on play", () => {
    let state = reduce(initialPlaybackState(recorded, 715), { type: "togglePlay", ...recorded });
    state = reduce(state, { type: "tick", seconds: 10, ...recorded });
    expect(state).toMatchObject({ cursor: 720, playing: false, following: false });
    state = reduce(state, { type: "togglePlay", ...recorded });
    expect(state).toMatchObject({ cursor: 0, playing: true });
  });

  it("scrubs within the frames", () => {
    let state = initialPlaybackState(recorded);
    state = reduce(state, { type: "seek", t: -50, ...recorded });
    expect(state.cursor).toBe(0);
    state = reduce(state, { type: "seek", t: 400, ...recorded });
    expect(state.cursor).toBe(400);
  });

  it("steps by one time step and pauses", () => {
    let state = reduce(initialPlaybackState(recorded, 100), { type: "togglePlay", ...recorded });
    state = reduce(state, { type: "step", direction: 1, step: 10, ...recorded });
    expect(state).toMatchObject({ cursor: 110, playing: false });
    state = reduce(state, { type: "step", direction: -1, step: 10, ...recorded });
    expect(state.cursor).toBe(100);
  });

  it("keeps the cursor inside a shrinking range", () => {
    let state = initialPlaybackState(recorded, 600);
    state = reduce(state, { type: "range", start: 0, end: 300, live: false });
    expect(state.cursor).toBe(300);
  });

  it("does not play a single frame", () => {
    const single: PlaybackRange = { start: 0, end: 0, live: false };
    const state = reduce(initialPlaybackState(single), { type: "togglePlay", ...single });
    expect(state.playing).toBe(false);
  });
});

describe("frameAtOrBefore", () => {
  const frames = [{ timestamp: 0 }, { timestamp: 10 }, { timestamp: 20 }];

  it("shows the last frame at or before the play head", () => {
    expect(frameAtOrBefore(frames, 15)?.timestamp).toBe(10);
    expect(frameAtOrBefore(frames, 20)?.timestamp).toBe(20);
    expect(frameAtOrBefore(frames, 99)?.timestamp).toBe(20);
    expect(frameAtOrBefore(frames, -5)?.timestamp).toBe(0);
    expect(frameAtOrBefore([], 5)).toBeNull();
  });
});
