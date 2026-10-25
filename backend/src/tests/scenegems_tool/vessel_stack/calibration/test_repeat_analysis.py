"""Deviation between repeats and pace, on synthetic tracks with known answers."""

import numpy as np
import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.calibration.repeat_analysis import TrackSamples, achieved_speedup, onset_time, repeat_deviation
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import StampedState


def line(start_s=0.0, end_s=60.0, step_s=0.04, speed=3.0, offset_y=0.0, wall_span_s=None, rest_s=0.0) -> TrackSamples:
    """A vessel that waits rest_s and then moves east at `speed`."""
    time_s = np.arange(start_s, end_s, step_s)
    moving = np.clip(time_s - start_s - rest_s, 0, None)
    return TrackSamples(time_s=time_s, x=speed * moving, y=np.full_like(time_s, offset_y), speed=np.where(time_s - start_s >= rest_s, speed, 0.0), wall_span_s=wall_span_s)


class TestTrack:
    def test_samples_must_have_one_length(self):
        with pytest.raises(ValueError, match="same number of samples"):
            TrackSamples(time_s=np.zeros(3), x=np.zeros(2), y=np.zeros(3), speed=np.zeros(3))

    def test_duration(self):
        assert line(0.0, 10.0).duration_s == pytest.approx(9.96)
        assert TrackSamples(np.array([]), np.array([]), np.array([]), np.array([])).duration_s == 0.0

    def test_from_stamped_samples_uses_seconds_since_the_epoch(self):
        samples = [StampedState(boot_ms=61_000 + 40 * index, state=ActorState(x=float(index), y=2.0, speed=1.5, heading=0.0)) for index in range(3)]
        track = TrackSamples.from_stamped(samples, epoch_boot_ms=60_000)
        np.testing.assert_allclose(track.time_s, [1.0, 1.04, 1.08])
        np.testing.assert_allclose(track.x, [0.0, 1.0, 2.0])
        np.testing.assert_allclose(track.speed, [1.5, 1.5, 1.5])


class TestPace:
    def test_onset_is_the_first_sample_above_the_threshold(self):
        assert onset_time(line(rest_s=5.0)) == pytest.approx(5.0)

    def test_a_vessel_that_never_moves_has_no_onset(self):
        assert onset_time(line(speed=0.1)) is None

    def test_achieved_speedup_is_simulated_over_wall_seconds(self):
        track = line(0.0, 100.0, wall_span_s=20.0)
        assert achieved_speedup(track) == pytest.approx(99.96 / 20.0)

    def test_without_wall_time_there_is_no_pace(self):
        assert achieved_speedup(line()) is None
        assert achieved_speedup(line(wall_span_s=0.0)) is None


class TestScenarioTimeDeviation:
    def test_identical_repeats_do_not_deviate(self):
        summary = repeat_deviation([line(), line(), line()])
        assert summary.max_m == 0.0 and summary.rms_m == 0.0
        assert summary.identical_prefix
        assert summary.repeats == 3
        assert summary.alignment == "scenario_time"
        assert summary.onset_spread_s is None

    def test_a_constant_offset_is_the_deviation(self):
        summary = repeat_deviation([line(), line(offset_y=0.5)])
        assert summary.max_m == pytest.approx(0.5)
        assert summary.rms_m == pytest.approx(0.5)
        assert not summary.identical_prefix

    def test_the_largest_pair_decides(self):
        summary = repeat_deviation([line(), line(offset_y=0.1), line(offset_y=-0.4)])
        assert summary.max_m == pytest.approx(0.5)

    def test_a_late_start_shows_as_a_growing_gap(self):
        summary = repeat_deviation([line(), line(rest_s=1.0)])
        assert summary.max_m == pytest.approx(3.0, abs=0.05), "one second late at 3 m/s"

    def test_the_compared_span_stays_inside_the_shortest_track(self):
        summary = repeat_deviation([line(end_s=60.0), line(end_s=30.0)])
        assert summary.compared_duration_s == pytest.approx(29.0, abs=1.0)

    def test_different_sampling_phases_interpolate_to_the_same_track(self):
        a = line(step_s=0.04)
        b = line(start_s=0.013, step_s=0.04)
        assert repeat_deviation([a, b]).max_m < 0.2

    def test_one_repeat_has_nothing_to_compare(self):
        assert repeat_deviation([line()]) is None

    def test_tracks_without_a_common_span_are_an_error(self):
        with pytest.raises(ValueError, match="no common time span"):
            repeat_deviation([line(0.0, 1.0), line(0.0, 1.0)])

    def test_unknown_alignment_is_an_error(self):
        with pytest.raises(ValueError, match="Unknown alignment 'wall'"):
            repeat_deviation([line(), line()], "wall")


class TestOnsetDeviation:
    def test_repeats_that_start_at_different_times_agree_when_aligned_on_the_onset(self):
        summary = repeat_deviation([line(rest_s=2.0), line(rest_s=5.0)], "onset")
        assert summary.max_m < 0.2
        assert summary.onset_spread_s == pytest.approx(3.0)
        assert summary.alignment == "onset"

    def test_the_same_repeats_deviate_in_scenario_time(self):
        assert repeat_deviation([line(rest_s=2.0), line(rest_s=5.0)], "scenario_time").max_m > 5.0

    def test_a_repeat_that_never_moves_cannot_be_aligned(self):
        assert repeat_deviation([line(), line(speed=0.1)], "onset") is None
