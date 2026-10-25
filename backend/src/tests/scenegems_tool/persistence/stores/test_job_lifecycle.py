from datetime import datetime, timedelta, timezone

import pytest

from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.stores.job_lifecycle import lease_is_current, result_status, state_after_failed_attempt
from scenegems_tool.persistence.stores.job_records import ResultStatus

NOW = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(seconds=30)


@pytest.mark.parametrize("state", [JobState.LEASED, JobState.RUNNING])
def test_active_unexpired_lease_is_current(state):
    assert lease_is_current(state, "lease-1", LATER, "lease-1", NOW)


def test_lease_ends_at_its_expiry_instant():
    assert not lease_is_current(JobState.RUNNING, "lease-1", NOW, "lease-1", NOW)


def test_other_lease_is_not_current():
    assert not lease_is_current(JobState.RUNNING, "lease-2", LATER, "lease-1", NOW)


@pytest.mark.parametrize("state", [JobState.QUEUED, JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED])
def test_lease_of_an_inactive_job_is_not_current(state):
    assert not lease_is_current(state, "lease-1", LATER, "lease-1", NOW)


def test_failed_attempts_requeue_until_the_limit():
    assert state_after_failed_attempt(1, 3) == JobState.QUEUED
    assert state_after_failed_attempt(2, 3) == JobState.QUEUED
    assert state_after_failed_attempt(3, 3) == JobState.FAILED


def test_non_retryable_failure_fails_at_once():
    assert state_after_failed_attempt(1, 3, retryable=False) == JobState.FAILED


def test_result_of_the_current_lease_is_stored():
    assert result_status(JobState.RUNNING, "lease-1", LATER, 1, None, "lease-1", NOW) == ResultStatus.STORED


def test_result_reported_twice_is_a_duplicate():
    assert result_status(JobState.SUCCEEDED, "lease-1", None, 1, 1, "lease-1", NOW) == ResultStatus.DUPLICATE


def test_repeated_retryable_failure_is_a_duplicate_while_requeued():
    assert result_status(JobState.QUEUED, "lease-1", None, 1, 1, "lease-1", NOW) == ResultStatus.DUPLICATE


def test_result_of_a_superseded_lease_is_stale():
    # attempt 1 failed and was stored; attempt 2 now runs under another lease
    assert result_status(JobState.RUNNING, "lease-2", LATER, 2, 1, "lease-1", NOW) == ResultStatus.STALE


def test_result_after_expiry_is_stale():
    assert result_status(JobState.RUNNING, "lease-1", NOW, 1, None, "lease-1", NOW) == ResultStatus.STALE


def test_result_after_cancel_is_stale():
    assert result_status(JobState.CANCELLED, "lease-1", None, 1, None, "lease-1", NOW) == ResultStatus.STALE
