"""The engine lock: one leader per database, released with its connection, no open transaction."""

from typing import Iterator, List

import pytest
from sqlalchemy import text

from scenegems_tool.assurance.pipeline.engine_leadership import ENGINE_LOCK, EngineLeadership, LeadershipLost
from scenegems_tool.persistence.database import transaction

pytestmark = pytest.mark.postgres


@pytest.fixture
def leaderships(session_factory) -> Iterator[List[EngineLeadership]]:
    made: List[EngineLeadership] = []
    yield made
    for leadership in made:
        leadership.release()


@pytest.fixture
def make_leadership(session_factory, leaderships):
    def make() -> EngineLeadership:
        leadership = EngineLeadership(session_factory)
        leaderships.append(leadership)
        return leadership

    return make


def _lock_holders(session_factory) -> List[int]:
    with transaction(session_factory) as session:
        rows = session.execute(
            text("SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted AND classid = CAST(:space AS oid) AND objid = CAST(:key AS oid) AND objsubid = 2"),
            {"space": ENGINE_LOCK[0], "key": ENGINE_LOCK[1]},
        )
        return [row.pid for row in rows]


def test_one_engine_leads_and_the_next_takes_over_after_a_release(session_factory, make_leadership):
    first, second = make_leadership(), make_leadership()
    assert first.acquire() and first.held and first.term == 1
    assert first.acquire() and first.term == 1  # a live lock stays the same term
    assert not second.acquire() and not second.held
    first.release()
    assert not first.held
    assert second.acquire() and second.term == 1
    assert not first.acquire()
    assert _lock_holders(session_factory) == [second._pid]


def test_holds_is_true_only_for_the_connection_that_has_the_lock(session_factory, make_leadership):
    first, second = make_leadership(), make_leadership()
    assert first.acquire() and not second.acquire()
    with transaction(session_factory) as session:
        assert first.holds(session) and not second.holds(session)
        first.check(session)
        with pytest.raises(LeadershipLost):
            second.check(session)
    first.release()
    with transaction(session_factory) as session:
        assert not first.holds(session)


def test_a_released_lock_does_not_go_back_to_the_pool(session_factory, make_leadership):
    leadership = make_leadership()
    assert leadership.acquire()
    leadership.release()
    assert _lock_holders(session_factory) == []
    with transaction(session_factory) as session:  # pooled connections hold no session lock either
        assert session.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()")).scalar() == 0


def test_the_lock_connection_keeps_no_transaction_open(session_factory, make_leadership):
    # An open transaction would hold back the snapshot horizon that the engine's cursor reads up to
    leadership = make_leadership()
    assert leadership.acquire()
    with transaction(session_factory) as session:
        state = session.execute(text("SELECT state FROM pg_stat_activity WHERE pid = :pid"), {"pid": leadership._pid}).scalar()
    assert state == "idle"


def test_a_lock_whose_connection_ended_is_taken_again_in_a_new_term(session_factory, make_leadership):
    leadership = make_leadership()
    assert leadership.acquire()
    old_pid = leadership._pid
    with transaction(session_factory) as session:
        assert session.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": old_pid}).scalar()
    assert leadership.acquire()
    assert leadership.term == 2 and leadership._pid != old_pid
    assert _lock_holders(session_factory) == [leadership._pid]


def test_a_lock_another_engine_took_meanwhile_is_not_taken_back(session_factory, make_leadership):
    first, second = make_leadership(), make_leadership()
    assert first.acquire()
    with transaction(session_factory) as session:
        session.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": first._pid})
    assert second.acquire()
    assert not first.acquire() and not first.held
