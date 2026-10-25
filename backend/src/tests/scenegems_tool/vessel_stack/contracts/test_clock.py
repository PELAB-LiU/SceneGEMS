"""LockstepClock and derive_seed: the clock contract of every simulation layer."""

import pytest

from scenegems_tool.vessel_stack.contracts.clock import LockstepClock, LockstepViolation, StepAck, StepRequest, derive_seed


def acks(clock: LockstepClock, *participants: str):
    return [StepAck(participant, clock.index) for participant in participants]


class TestClock:
    def test_time_is_the_step_index_times_dt(self):
        clock = LockstepClock(0.25, ["a"])
        assert clock.time == 0.0
        clock.advance(acks(clock, "a"))
        clock.advance(acks(clock, "a"))
        assert clock.time == 0.5

    def test_time_is_exact_for_a_decimal_dt_after_many_steps(self):
        clock = LockstepClock(0.1, ["a"])
        for _ in range(10_000):
            clock.advance(acks(clock, "a"))
        assert clock.time == 10_000 * 0.1
        assert clock.request().target_time == 10_001 * 0.1

    def test_request_covers_one_step(self):
        clock = LockstepClock(2.0, ["a"])
        assert clock.request() == StepRequest(index=0, time=0.0, target_time=2.0)
        clock.advance(acks(clock, "a"))
        assert clock.request() == StepRequest(index=1, time=2.0, target_time=4.0)

    def test_request_does_not_advance(self):
        clock = LockstepClock(1.0, ["a"])
        clock.request()
        clock.request()
        assert clock.index == 0

    @pytest.mark.parametrize("dt", [0, -1.0])
    def test_dt_must_be_positive(self, dt):
        with pytest.raises(ValueError, match="dt must be positive"):
            LockstepClock(dt, ["a"])

    def test_participants_are_sorted_and_unique(self):
        assert LockstepClock(1.0, ["b", "a", "b"]).participant_ids == ("a", "b")

    def test_advance_returns_the_new_time(self):
        clock = LockstepClock(1.0, ["a"])
        assert clock.advance(acks(clock, "a")) == 1.0


class TestViolations:
    def test_every_participant_must_acknowledge(self):
        clock = LockstepClock(1.0, ["a", "b"])
        with pytest.raises(LockstepViolation, match="missing acknowledgements from b"):
            clock.advance(acks(clock, "a"))
        assert clock.index == 0

    def test_all_missing_participants_are_named(self):
        clock = LockstepClock(1.0, ["a", "b", "c"])
        with pytest.raises(LockstepViolation, match="missing acknowledgements from b, c"):
            clock.advance(acks(clock, "a"))

    def test_an_acknowledgement_of_another_step_is_rejected(self):
        clock = LockstepClock(1.0, ["a"])
        with pytest.raises(LockstepViolation, match="acknowledged step 3 while the clock is at step 0"):
            clock.advance([StepAck("a", 3)])

    def test_an_unknown_participant_is_rejected(self):
        clock = LockstepClock(1.0, ["a"])
        with pytest.raises(LockstepViolation, match="z is not a participant"):
            clock.advance(acks(clock, "a", "z"))

    def test_an_acknowledgement_for_the_previous_step_is_stale(self):
        clock = LockstepClock(1.0, ["a"])
        clock.advance(acks(clock, "a"))
        with pytest.raises(LockstepViolation):
            clock.advance([StepAck("a", 0)])

    def test_duplicate_acknowledgements_count_once(self):
        clock = LockstepClock(1.0, ["a"])
        clock.advance(acks(clock, "a", "a"))
        assert clock.index == 1

    def test_a_clock_without_participants_advances_freely(self):
        clock = LockstepClock(1.0, [])
        clock.advance([])
        assert clock.index == 1


class TestDeriveSeed:
    def test_known_value(self):
        # A SHA-256 based constant, the same in every process (hash() would differ).
        assert derive_seed(0, "replay/0") == 14040935488756608327

    def test_depends_on_run_seed_and_component(self):
        assert derive_seed(0, "a") != derive_seed(1, "a")
        assert derive_seed(0, "a") != derive_seed(0, "b")

    def test_fits_in_64_bits(self):
        assert 0 <= derive_seed(123456789, "component") < 2**64
