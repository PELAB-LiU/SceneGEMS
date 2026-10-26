"""Deviation between repeats and pace, from sampled tracks.

A track is one vessel's position over simulated time, as one repeat of a run recorded it.
Repeats are compared on a common time grid in one of two alignments:

- scenario_time: equal simulated time since scenario time 0. This is how the lockstep adapter
  runs are compared (design doc 12.8), since the adapter fixes the scenario clock.
- onset: equal time since the vessel started to move. This is how the Phase 0 driver runs
  were compared (design doc 10.5), because a single target sent at an arbitrary instant
  gives no common scenario clock.

The functions are pure, so the numbers behind a bounded tier can be checked without a simulator.

How well one track follows its reference trajectory (tracking_error) is measured against the
reference path, not the reference point at the same time, so a vessel that lags along the path
is not counted as off it: the cross-track error is the distance to the nearest segment of the
reference polyline, taken on the straight legs only (settle_s after the end of every turn).
An orbit shows as a net heading change that differs from the reference's by a full turn.
"""

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import StampedState

ONSET_SPEED_M_S = 0.3  # a vessel moves once its speed exceeds this
GRID_STEP_S = 0.5
IDENTICAL_PREFIX_SAMPLES = 50  # Phase 0 called a run bit-identical when its first samples were
STRAIGHT_TURN_RATE = math.radians(0.1)  # rad/s: a reference sample turning slower than this is on a straight leg
ORBIT_EXCESS_TURN_DEG = 270.0  # a track whose net heading change differs from the reference's by this much orbited


@dataclass(frozen=True)
class TrackSamples:
    time_s: np.ndarray  # simulated seconds, increasing
    x: np.ndarray  # local frame, meters
    y: np.ndarray
    speed: np.ndarray  # m/s
    wall_span_s: Optional[float] = None  # wall seconds from the first to the last sample, for the pace only
    heading: Optional[np.ndarray] = None  # radians, counterclockwise from east, when the source reports it

    def __post_init__(self) -> None:
        lengths = {len(self.time_s), len(self.x), len(self.y), len(self.speed)} | ({len(self.heading)} if self.heading is not None else set())
        if len(lengths) != 1:
            raise ValueError(f"time, x, y, speed and heading need the same number of samples, got {sorted(lengths)}")

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
            heading=np.array([float(sample.state.heading) for sample in samples]),
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


@dataclass(frozen=True)
class TrackingSummary:
    max_cross_track_m: float  # largest distance from the reference path on its straight legs
    rms_cross_track_m: float  # on the straight legs
    max_cross_track_anywhere_m: float  # turns and their settling included
    max_along_track_lag_m: float  # how far behind the reference point at the same time the vessel fell, after settle_s
    final_along_track_m: float  # signed (negative: behind) at the end of the compared span
    excess_turn_deg: float  # net heading change of the track minus that of the reference, over the compared span
    straight_samples: int
    compared_duration_s: float

    @property
    def orbited(self) -> bool:
        return abs(self.excess_turn_deg) >= ORBIT_EXCESS_TURN_DEG


def _unwrapped_net_turn(heading: np.ndarray) -> float:
    return float(np.unwrap(heading)[-1] - np.unwrap(heading)[0]) if len(heading) > 1 else 0.0


def _track_heading(track: TrackSamples) -> np.ndarray:
    if track.heading is not None:
        return track.heading
    return np.arctan2(np.gradient(track.y), np.gradient(track.x))


def _straight_reference_indices(reference_heading: np.ndarray, time_step_s: float, settle_s: float) -> np.ndarray:
    """Reference samples on a straight leg: no turning there, and none within settle_s before them."""
    turn_rate = np.abs(np.diff(np.unwrap(reference_heading))) / time_step_s
    turning = np.concatenate([[False], turn_rate > STRAIGHT_TURN_RATE])
    settle = int(math.ceil(settle_s / time_step_s))
    straight = ~turning.copy()
    for index in np.nonzero(turning)[0]:
        straight[index : index + settle + 1] = False
    return straight


def _distance_to_path(px: np.ndarray, py: np.ndarray, path_x: np.ndarray, path_y: np.ndarray, chunk: int = 512):
    """Distance from every point to the polyline, the segment it is nearest to, and where on that segment (0 to 1)."""
    ax, ay = path_x[:-1], path_y[:-1]
    dx, dy = path_x[1:] - ax, path_y[1:] - ay
    length2 = np.maximum(dx * dx + dy * dy, 1e-12)
    distances, segments, fractions = [], [], []
    for start in range(0, len(px), chunk):
        rel_x = px[start : start + chunk, None] - ax[None, :]
        rel_y = py[start : start + chunk, None] - ay[None, :]
        fraction = np.clip((rel_x * dx + rel_y * dy) / length2, 0.0, 1.0)
        distance = np.hypot(rel_x - fraction * dx, rel_y - fraction * dy)
        nearest = np.argmin(distance, axis=1)
        rows = np.arange(len(nearest))
        distances.append(distance[rows, nearest])
        segments.append(nearest)
        fractions.append(fraction[rows, nearest])
    return np.concatenate(distances), np.concatenate(segments), np.concatenate(fractions)


def tracking_error(track: TrackSamples, reference: Sequence[ActorState], time_step_s: float, settle_s: float = 20.0) -> TrackingSummary:
    """How closely a track (scenario time since t = 0) follows the reference states sampled every time_step_s.

    Track samples before scenario time 0 or after the end of the reference are left out. A track
    sample counts toward the straight-leg error when the reference point it is nearest to lies on
    a straight leg (_straight_reference_indices); the vessel's own speed-up from rest does not count
    as a turn.
    """
    if len(reference) < 2:
        raise ValueError("the reference needs at least two states")
    ref_x = np.array([float(state.x) for state in reference])
    ref_y = np.array([float(state.y) for state in reference])
    ref_heading = np.array([float(state.heading) for state in reference])
    ref_time = np.arange(len(reference)) * time_step_s
    inside = (track.time_s >= 0.0) & (track.time_s <= ref_time[-1])
    if not np.any(inside):
        raise ValueError("the track has no sample inside the reference's time span")
    time_s, x, y = track.time_s[inside], track.x[inside], track.y[inside]
    heading = _track_heading(track)[inside]

    distance, nearest, fraction = _distance_to_path(x, y, ref_x, ref_y)
    straight_reference = _straight_reference_indices(ref_heading, time_step_s, settle_s)
    nearest_index = np.where(fraction < 0.5, nearest, nearest + 1)
    on_straight = straight_reference[nearest_index]

    # Along-track error against the reference point at the same scenario time.
    ref_x_t, ref_y_t = np.interp(time_s, ref_time, ref_x), np.interp(time_s, ref_time, ref_y)
    ref_heading_t = np.interp(time_s, ref_time, np.unwrap(ref_heading))
    along = np.cos(ref_heading_t) * (x - ref_x_t) + np.sin(ref_heading_t) * (y - ref_y_t)
    settled = time_s >= settle_s
    reference_turn = float(np.unwrap(ref_heading)[np.searchsorted(ref_time, time_s[-1], side="right") - 1] - np.unwrap(ref_heading)[np.searchsorted(ref_time, time_s[0], side="right") - 1])

    straight = distance[on_straight]
    return TrackingSummary(
        max_cross_track_m=float(straight.max()) if len(straight) else 0.0,
        rms_cross_track_m=float(np.sqrt(np.mean(straight**2))) if len(straight) else 0.0,
        max_cross_track_anywhere_m=float(distance.max()),
        max_along_track_lag_m=float(max(0.0, -along[settled].min())) if np.any(settled) else 0.0,
        final_along_track_m=float(along[-1]),
        excess_turn_deg=math.degrees(_unwrapped_net_turn(heading) - reference_turn),
        straight_samples=int(np.count_nonzero(on_straight)),
        compared_duration_s=float(time_s[-1] - time_s[0]),
    )
