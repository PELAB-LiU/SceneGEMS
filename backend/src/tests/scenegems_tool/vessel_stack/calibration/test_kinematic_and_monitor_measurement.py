"""The in-process measurements: kinematic reproducibility and pace, and the COLREGS monitor."""

import math

import pytest

from scenegems_tool.vessel_stack.calibration.kinematic_measurement import KinematicMeasurement, measure_kinematic
from scenegems_tool.vessel_stack.calibration.monitor_measurement import MonitorMeasurement, frames_digest, load_constants, measure_monitor, monitor_scenes
from scenegems_tool.vessel_stack.calibration.reference_scenarios import encounter_trajectories


class TestKinematic:
    @pytest.fixture(scope="module")
    def usv_navigation(self):
        return measure_kinematic("usv_navigation", "crossing_from_starboard", timespan=300, repeats=2, hash_seeds=("0",))

    def test_repeats_and_a_fresh_process_agree(self, usv_navigation):
        assert usv_navigation.reproducible
        assert len(usv_navigation.digests) == 2
        assert set(usv_navigation.process_digests) == {"0"}
        assert usv_navigation.digests[0] == usv_navigation.process_digests["0"]

    def test_pace_is_measured(self, usv_navigation):
        assert usv_navigation.steps_per_second > 0
        assert usv_navigation.speed_relative_to_real_time == pytest.approx(usv_navigation.steps_per_second * usv_navigation.dt)

    def test_a_reproducible_run_claims_the_exact_tier_and_no_speed_limit(self, usv_navigation):
        entry = usv_navigation.entry()
        assert entry.spec_id == "usv_navigation_in_process"
        assert entry.fields["repeatability_tier"] == "exact"
        assert math.isinf(entry.fields["max_speedup"])
        assert "digests identical" in entry.fields["evidence"]
        entry.parsed()
        entry.check_registered()

    def test_replay_measures_the_kinematic_adapter(self):
        measurement = measure_kinematic("replay", "head_on", timespan=60, repeats=2, hash_seeds=())
        assert measurement.entry().spec_id == "kinematic_command_input"
        assert measurement.process_digests == {}
        assert measurement.reproducible

    def test_differing_digests_do_not_claim_exact(self):
        measurement = KinematicMeasurement("replay", "head_on", steps=10, dt=1.0, repeats=2, digests=["a", "b"])
        assert not measurement.reproducible
        entry = measurement.entry()
        assert entry.fields["repeatability_tier"] == "bounded"
        assert "max_speedup" not in entry.fields
        assert "DIFFER" in entry.fields["evidence"]

    def test_a_process_that_differs_breaks_reproducibility(self):
        measurement = KinematicMeasurement("replay", "head_on", steps=10, dt=1.0, repeats=1, digests=["a"], process_digests={"1": "b"})
        assert not measurement.reproducible

    def test_unknown_mode_and_encounter_are_rejected(self):
        with pytest.raises(ValueError, match="Unknown mode 'fly'"):
            measure_kinematic("fly")
        with pytest.raises(ValueError, match="Unknown encounter 'collision'"):
            measure_kinematic("replay", "collision")


class TestMonitor:
    @pytest.fixture(scope="module")
    def measurement(self):
        return measure_monitor("head_on", timespan=120, repeats=2, hash_seeds=())

    def test_every_scene_is_monitored_and_timed(self, measurement):
        assert measurement.scenes == 121
        assert len(measurement.repeat_seconds) == 2
        assert measurement.scenes_per_second > 0

    def test_repeats_in_one_process_give_identical_frames(self, measurement):
        assert measurement.reproducible_in_process
        assert measurement.reproducible_across_processes is None

    def test_a_fresh_process_is_compared_with_the_in_process_digest(self):
        measurement = measure_monitor("head_on", timespan=60, repeats=1, hash_seeds=("0",))
        assert set(measurement.process_digests) == {"0"}
        # Whether the digests agree is the finding of design doc 10.6, item 2 (rule lists follow set order);
        # the measurement reports it, so it is not asserted here.
        assert measurement.reproducible_across_processes in (True, False)

    def test_as_dict_is_json_ready(self, measurement):
        import json

        data = measurement.as_dict()
        assert data["reproducible_in_process"] is True
        json.dumps(data)

    def test_frames_digest_depends_on_the_scenes(self):
        constants = load_constants()
        first = frames_digest(monitor_scenes(encounter_trajectories("head_on", 30).scene_list, constants))
        second = frames_digest(monitor_scenes(encounter_trajectories("overtaking", 30).scene_list, constants))
        assert first != second

    def test_unknown_encounter_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown encounter"):
            measure_monitor("collision")

    def test_reproducibility_flags(self):
        measurement = MonitorMeasurement("head_on", 10, "c.yaml", repeat_seconds=[1.0], digests=["a", "b"])
        assert not measurement.reproducible_in_process
        measurement = MonitorMeasurement("head_on", 10, "c.yaml", repeat_seconds=[2.0, 1.0], digests=["a"], process_digests={"0": "a", "1": "b"})
        assert measurement.reproducible_in_process
        assert measurement.reproducible_across_processes is False
        assert measurement.scenes_per_second == 10.0
