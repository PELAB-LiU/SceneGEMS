"""Deviation between repeats and pace, from sampled tracks.

A track is one vessel's position over simulated time, as one repeat of a run recorded it.
Repeats are compared on a common time grid in one of two alignments:

- scenario_time: equal simulated time since scenario time 0. This is how the lockstep adapter
  runs are compared (design doc 12.8), since the adapter fixes the scenario clock.
- onset: equal time since the vessel started to move. This is how the Phase 0 driver runs
  were compared (design doc 10.5), because a single target sent at an arbitrary instant
  gives no common scenario clock.

The functions are pure, so the numbers behind a bounded tier can be checked without a simulator.
"""

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import StampedState

ONSET_SPEED_M_S = 0.3  # a vessel moves once its speed exceeds this
GRID_STEP_S = 0.5
IDENTICAL_PREFIX_SAMPLES = 50  # Phase 0 called a run bit-identical when its first samples were


@dataclass(frozen=True)
class TrackSamples:
    time_s: np.ndarray  # simulated seconds, increasing
    x: np.ndarray  # local frame, meters
    y: np.ndarray
    speed: np.ndarray  # m/s
    wall_span_s: Optional[float] = None  # wall seconds from the first to the last sample, for the pace only

    def __post_init__(self) -> None:
        lengths = {len(self.time_s), len(self.x), len(self.y), len(self.speed)}
        if len(lengths) != 1:
            raise ValueError(f"time, x, y and speed need the same number of samples, got {sorted(lengths)}")

    @property
    def duration_s(self) -> float:
        return float(self.time_s[-1] - self.time_s[0]) if len(self.time_s) else 0.0

    @classmethod
    def from_stamped(cls, samples: Sequence[StampedState], epoch_boot_ms: int = 0) -> "TrackSamples":
        """Link samples (SITL time stamped) as a track whose time is seconds since epoch_boot_ms."""
        return cls(
            time_s=np.array([(sample.boot_ms - epoch_boot_ms) / 1000.0 for sample in samples]),
            x=np.array([float(sample.state.x) for sample in samples]),
            y=np.array([float(sample.state.y) for sample in samples]),
            speed=np.array([float(sample.state.speed) for sample in samples]),
        )


@dataclass(frozen=True)
class DeviationSummary:
    alignment: str
    repeats: int
    max_m: float  # largest distance between any two repeats at the same aligned time
    rms_m: float
    compared_duration_s: float
    onset_spread_s: Optional[float]  # largest difference between the repeats' onset times, onset alignment only
    identical_prefix: bool  # the first samples of every repeat are equal


def onset_time(track: TrackSamples, threshold: float = ONSET_SPEED_M_S) -> Optional[float]:
    """Simulated time at which the track first moves faster than the threshold, None if it never does."""
    above = np.nonzero(track.speed > threshold)[0]
    return float(track.time_s[above[0]]) if len(above) else None


def achieved_speedup(track: TrackSamples) -> Optional[float]:
    """Simulated seconds per wall second over the track; None without a wall time span."""
    if track.wall_span_s is None or track.wall_span_s <= 0:
        return None
    return track.duration_s / track.wall_span_s


def _grid_tracks(tracks: Sequence[TrackSamples], alignment: str, step_s: float):
    if alignment == "scenario_time":
        starts = [max(float(track.time_s[0]), 0.0) for track in tracks]
        origins = [0.0] * len(tracks)
        onsets = None
    elif alignment == "onset":
        onsets = [onset_time(track) for track in tracks]
        if any(onset is None for onset in onsets):
            return None, None
        origins = [float(onset) for onset in onsets]
        starts = [0.0] * len(tracks)
    else:
        raise ValueError(f"Unknown alignment '{alignment}'; expected scenario_time or onset")
    length = min(float(track.time_s[-1]) - origin for track, origin in zip(tracks, origins))
    first = max(starts)
    # Stay one second inside the shortest track so that interpolation never leans on its last sample.
    grid = np.arange(first, length - 1.0, step_s)
    if len(grid) == 0:
        raise ValueError("the repeats have no common time span to compare")
    stacked = [np.stack([np.interp(grid + origin, track.time_s, track.x), np.interp(grid + origin, track.time_s, track.y)]) for track, origin in zip(tracks, origins)]
    return stacked, onsets


def repeat_deviation(tracks: Sequence[TrackSamples], alignment: str = "scenario_time", step_s: float = GRID_STEP_S) -> Optional[DeviationSummary]:
    """Largest and rms distance between the repeats on the common time grid; None when the alignment is impossible.

    Onset alignment is impossible when a repeat never moves. One repeat has nothing to compare with.
    """
    if len(tracks) < 2:
        return None
    stacked, onsets = _grid_tracks(tracks, alignment, step_s)
    if stacked is None:
        return None
    distances = [np.hypot(*(stacked[i] - stacked[j])) for i in range(len(stacked)) for j in range(i + 1, len(stacked))]
    count = min(IDENTICAL_PREFIX_SAMPLES, *(len(track.time_s) for track in tracks))
    identical = all(
        np.array_equal(track.time_s[:count], tracks[0].time_s[:count]) and np.array_equal(track.x[:count], tracks[0].x[:count]) and np.array_equal(track.y[:count], tracks[0].y[:count])
        for track in tracks[1:]
    )
    return DeviationSummary(
        alignment=alignment,
        repeats=len(tracks),
        max_m=float(max(distance.max() for distance in distances)),
        rms_m=math.sqrt(float(np.mean([np.mean(distance**2) for distance in distances]))),
        compared_duration_s=float(step_s * len(distances[0])),
        onset_spread_s=float(max(onsets) - min(onsets)) if onsets else None,
        identical_prefix=bool(identical),
    )
