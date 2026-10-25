from scenegems_tool.persistence.stores import START_OF_EVENTS, CursorPosition
from scenegems_tool.persistence.stores.case_store import COUNT_COLUMN_OF_STATE, UNSET
from scenegems_tool.persistence.schema import CaseState


def test_cursor_positions_order_by_transaction_then_event():
    assert START_OF_EVENTS == CursorPosition(0, 0)
    assert CursorPosition(5, 100) < CursorPosition(6, 1) < CursorPosition(6, 2)
    assert max(CursorPosition(7, 1), CursorPosition(6, 900)) == CursorPosition(7, 1)


def test_every_case_state_but_cancelled_has_a_count():
    assert set(COUNT_COLUMN_OF_STATE) == set(CaseState) - {CaseState.CANCELLED}
    assert COUNT_COLUMN_OF_STATE[CaseState.FAILED] == COUNT_COLUMN_OF_STATE[CaseState.DROPPED] == "dropped_count"


def test_unset_is_distinct_from_none():
    assert UNSET is not None and repr(UNSET) == "UNSET"
