"""Classes and cases of a campaign: case creation, optimistic moves between stages and states, counts.

A class's counts follow its cases: every creation and every state change of a case updates
them in the same transaction (active cases count as in flight, complete as complete,
dropped and failed as dropped, cancelled in none), so they never drift from the cases.
recount_classes rebuilds them from the cases, for checks after a restart.

A case is moved with the version it was read at. When another writer changed it since,
move_case raises CaseConflict and changes nothing. A final case (complete, dropped, failed,
cancelled) keeps its state; its other fields (artifacts after retention, progress) may
still change.

Every method takes an optional session (see store_session).
"""

from typing import Any, Collection, Dict, List, Optional, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.schema import CampaignClassRow, CampaignClassState, CaseState, PipelineStage, ScenarioCaseRow
from scenegems_tool.persistence.schema.artifact_tables import require_sha256_hex
from scenegems_tool.persistence.stores.campaign_records import CaseRecord, ClassCounts, ClassRecord, NewCase
from scenegems_tool.persistence.stores.store_session import session_scope

# The class count each case state adds to; cancelled cases count in none
COUNT_COLUMN_OF_STATE = {
    CaseState.ACTIVE: "in_flight_count",
    CaseState.COMPLETE: "complete_count",
    CaseState.DROPPED: "dropped_count",
    CaseState.FAILED: "dropped_count",
}


class UnknownClass(LookupError):
    pass


class UnknownCase(LookupError):
    pass


class ClassStateConflict(ValueError):
    pass


class CaseConflict(ValueError):
    """The case changed since it was read, or is not in the expected stage or state."""

    def __init__(self, message: str, current: Optional[CaseRecord]):
        super().__init__(message)
        self.current = current


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()  # leaves a field of move_case as it is


def _check_move(row: ScenarioCaseRow, expected_version: int, expected_stage: Optional[PipelineStage], expected_state: Optional[CaseState], new_state: CaseState) -> None:
    problem = None
    if row.version != expected_version:
        problem = f"is at version {row.version}, not {expected_version}"
    elif expected_stage is not None and row.stage != expected_stage:
        problem = f"is at stage {row.stage.value}, not {expected_stage.value}"
    elif expected_state is not None and row.state != expected_state:
        problem = f"is {row.state.value}, not {expected_state.value}"
    elif row.state.is_final and new_state != row.state:
        problem = f"is {row.state.value} and stays so"
    if problem is not None:
        raise CaseConflict(f"case {row.id} {problem}", CaseRecord.from_row(row))


class CaseStore:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock = utc_now):
        self._sessions = session_factory
        self._clock = clock

    # Classes

    def get_class(self, campaign_id: str, class_id: str, *, lock: bool = False, session: Optional[Session] = None) -> Optional[ClassRecord]:
        with session_scope(self._sessions, session) as scope:
            row = self._load_class(scope, campaign_id, class_id, lock)
            return None if row is None else ClassRecord.from_row(row)

    def list_classes(self, campaign_id: str, states: Optional[Collection[CampaignClassState]] = None, *, session: Optional[Session] = None) -> List[ClassRecord]:
        """The campaign's classes ordered by class id, optionally only those in the given states."""
        with session_scope(self._sessions, session) as scope:
            query = select(CampaignClassRow).where(CampaignClassRow.campaign_id == campaign_id).order_by(CampaignClassRow.class_id)
            if states is not None:
                query = query.where(CampaignClassRow.state.in_(list(states)))
            return [ClassRecord.from_row(row) for row in scope.execute(query.execution_options(populate_existing=True)).scalars()]

    def set_class_state(
        self,
        campaign_id: str,
        class_id: str,
        state: CampaignClassState,
        reason: Optional[str] = None,
        expected: Optional[CampaignClassState] = None,
        *,
        session: Optional[Session] = None,
    ) -> ClassRecord:
        """Closes a class as complete or abandoned (or sets the state it has). A closed class stays closed."""
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            row = self._require_class(scope, campaign_id, class_id, lock=True)
            if expected is not None and row.state != expected:
                raise ClassStateConflict(f"class {class_id} of campaign {campaign_id} is {row.state.value}, not {expected.value}")
            if row.state == state:
                return ClassRecord.from_row(row)
            if row.state != CampaignClassState.OPEN:
                raise ClassStateConflict(f"class {class_id} of campaign {campaign_id} is {row.state.value} and stays so")
            row.state = state
            row.state_reason = reason
            row.updated_at = now
            row.finished_at = now
            scope.flush()
            return ClassRecord.from_row(row)

    def class_counts_from_cases(self, campaign_id: str, *, session: Optional[Session] = None) -> Dict[str, ClassCounts]:
        """Counts of every class of the campaign, counted from its cases instead of read from the class."""
        with session_scope(self._sessions, session) as scope:
            counts: Dict[str, Dict[str, int]] = {class_id: {} for class_id in scope.execute(select(CampaignClassRow.class_id).where(CampaignClassRow.campaign_id == campaign_id)).scalars()}
            query = select(ScenarioCaseRow.class_id, ScenarioCaseRow.state, func.count()).where(ScenarioCaseRow.campaign_id == campaign_id).group_by(ScenarioCaseRow.class_id, ScenarioCaseRow.state)
            for class_id, state, count in scope.execute(query):
                column = COUNT_COLUMN_OF_STATE.get(state)
                if column is not None:
                    counts[class_id][column] = counts[class_id].get(column, 0) + count
            return {
                class_id: ClassCounts(complete=values.get("complete_count", 0), dropped=values.get("dropped_count", 0), in_flight=values.get("in_flight_count", 0))
                for class_id, values in sorted(counts.items())
            }

    def recount_classes(self, campaign_id: str, *, session: Optional[Session] = None) -> List[ClassRecord]:
        """Sets the stored counts of every class from its cases; returns the classes whose counts were off."""
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            counted = self.class_counts_from_cases(campaign_id, session=scope)
            corrected = []
            rows = scope.execute(select(CampaignClassRow).where(CampaignClassRow.campaign_id == campaign_id).order_by(CampaignClassRow.class_id).with_for_update(key_share=True)).scalars()
            for row in rows:
                counts = counted.get(row.class_id, ClassCounts())
                if (row.complete_count, row.dropped_count, row.in_flight_count) != (counts.complete, counts.dropped, counts.in_flight):
                    row.complete_count, row.dropped_count, row.in_flight_count = counts.complete, counts.dropped, counts.in_flight
                    row.updated_at = now
                    corrected.append(row)
            scope.flush()
            return [ClassRecord.from_row(row) for row in corrected]

    # Cases

    def create_cases(self, campaign_id: str, cases: Sequence[NewCase], *, session: Optional[Session] = None) -> List[CaseRecord]:
        """Creates active cases in open classes of the campaign; their classes count them in flight.

        Raises UnknownClass for a class the campaign does not have, ClassStateConflict for a
        closed one; an index taken already violates the unique constraint.
        """
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            for class_id in sorted({case.class_id for case in cases}):
                row = self._require_class(scope, campaign_id, class_id, lock=True)
                if row.state != CampaignClassState.OPEN:
                    raise ClassStateConflict(f"class {class_id} of campaign {campaign_id} is {row.state.value}; it takes no new cases")
            rows = [
                ScenarioCaseRow(
                    campaign_id=campaign_id,
                    class_id=case.class_id,
                    case_index=case.case_index,
                    seed=case.seed,
                    config_version=case.config_version,
                    stage=case.stage,
                    state=CaseState.ACTIVE,
                    version=1,
                    progress={},
                    created_at=now,
                    updated_at=now,
                )
                for case in cases
            ]
            scope.add_all(rows)
            scope.flush()
            for row in rows:
                self._count(scope, campaign_id, row.class_id, CaseState.ACTIVE, 1, now)
            return [CaseRecord.from_row(row) for row in rows]

    def create_case(self, campaign_id: str, case: NewCase, *, session: Optional[Session] = None) -> CaseRecord:
        (record,) = self.create_cases(campaign_id, [case], session=session)
        return record

    def get_case(self, case_id: int, *, session: Optional[Session] = None) -> Optional[CaseRecord]:
        with session_scope(self._sessions, session) as scope:
            row = scope.get(ScenarioCaseRow, case_id, populate_existing=True)
            return None if row is None else CaseRecord.from_row(row)

    def find_case(self, campaign_id: str, class_id: str, case_index: int, *, session: Optional[Session] = None) -> Optional[CaseRecord]:
        with session_scope(self._sessions, session) as scope:
            query = select(ScenarioCaseRow).where(ScenarioCaseRow.campaign_id == campaign_id, ScenarioCaseRow.class_id == class_id, ScenarioCaseRow.case_index == case_index)
            row = scope.execute(query).scalar_one_or_none()
            return None if row is None else CaseRecord.from_row(row)

    def list_cases(
        self,
        campaign_id: str,
        class_id: Optional[str] = None,
        states: Optional[Collection[CaseState]] = None,
        stages: Optional[Collection[PipelineStage]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        session: Optional[Session] = None,
    ) -> List[CaseRecord]:
        """Cases of the campaign ordered by class and index, optionally of one class, in some states or stages."""
        with session_scope(self._sessions, session) as scope:
            query = select(ScenarioCaseRow).where(ScenarioCaseRow.campaign_id == campaign_id)
            if class_id is not None:
                query = query.where(ScenarioCaseRow.class_id == class_id)
            if states is not None:
                query = query.where(ScenarioCaseRow.state.in_(list(states)))
            if stages is not None:
                query = query.where(ScenarioCaseRow.stage.in_(list(stages)))
            query = query.order_by(ScenarioCaseRow.class_id, ScenarioCaseRow.case_index).offset(offset).limit(limit).execution_options(populate_existing=True)
            return [CaseRecord.from_row(row) for row in scope.execute(query).scalars()]

    def count_cases(self, campaign_id: str, states: Optional[Collection[CaseState]] = None, *, session: Optional[Session] = None) -> int:
        with session_scope(self._sessions, session) as scope:
            query = select(func.count()).select_from(ScenarioCaseRow).where(ScenarioCaseRow.campaign_id == campaign_id)
            if states is not None:
                query = query.where(ScenarioCaseRow.state.in_(list(states)))
            return scope.execute(query).scalar_one()

    def next_case_index(self, campaign_id: str, class_id: str, *, session: Optional[Session] = None) -> int:
        """One past the highest case index of the class, 0 for a class without cases."""
        with session_scope(self._sessions, session) as scope:
            query = select(func.max(ScenarioCaseRow.case_index)).where(ScenarioCaseRow.campaign_id == campaign_id, ScenarioCaseRow.class_id == class_id)
            highest = scope.execute(query).scalar_one()
            return 0 if highest is None else highest + 1

    def move_case(
        self,
        case_id: int,
        expected_version: int,
        *,
        stage: Optional[PipelineStage] = None,
        state: Optional[CaseState] = None,
        expected_stage: Optional[PipelineStage] = None,
        expected_state: Optional[CaseState] = None,
        scene_artifact: Any = UNSET,
        trajectories_artifact: Any = UNSET,
        trajectories_complete: Any = UNSET,
        progress: Any = UNSET,
        reason: Any = UNSET,
        session: Optional[Session] = None,
    ) -> CaseRecord:
        """Moves the case to a stage and state and sets the given fields, if it is still at expected_version.

        stage and state default to the case's own; fields left UNSET keep their value.
        Raises UnknownCase, or CaseConflict when the version, expected_stage or
        expected_state do not match, or when a final case would change its state.
        """
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            row = scope.execute(select(ScenarioCaseRow).where(ScenarioCaseRow.id == case_id).with_for_update(key_share=True).execution_options(populate_existing=True)).scalar_one_or_none()
            if row is None:
                raise UnknownCase(case_id)
            new_state = row.state if state is None else state
            _check_move(row, expected_version, expected_stage, expected_state, new_state)
            if stage is not None:
                row.stage = stage
            for name, value in (("scene_artifact", scene_artifact), ("trajectories_artifact", trajectories_artifact)):
                if value is not UNSET:
                    setattr(row, name, None if value is None else require_sha256_hex(value))
            for name, value in (("trajectories_complete", trajectories_complete), ("progress", progress), ("reason", reason)):
                if value is not UNSET:
                    setattr(row, name, dict(value) if name == "progress" else value)
            if new_state != row.state:
                self._count(scope, row.campaign_id, row.class_id, row.state, -1, now)
                self._count(scope, row.campaign_id, row.class_id, new_state, 1, now)
                row.state = new_state
                if new_state.is_final:
                    row.finished_at = now
            row.version += 1
            row.updated_at = now
            scope.flush()
            return CaseRecord.from_row(row)

    # Helpers

    @staticmethod
    def _count(session: Session, campaign_id: str, class_id: str, state: CaseState, delta: int, now) -> None:
        column = COUNT_COLUMN_OF_STATE.get(state)
        if column is None:
            return
        counter = getattr(CampaignClassRow, column)
        session.execute(
            update(CampaignClassRow)
            .where(CampaignClassRow.campaign_id == campaign_id, CampaignClassRow.class_id == class_id)
            .values({column: counter + delta, "updated_at": now})
            .execution_options(synchronize_session=False)
        )

    @staticmethod
    def _load_class(session: Session, campaign_id: str, class_id: str, lock: bool = False) -> Optional[CampaignClassRow]:
        query = select(CampaignClassRow).where(CampaignClassRow.campaign_id == campaign_id, CampaignClassRow.class_id == class_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update(key_share=True)
        return session.execute(query).scalar_one_or_none()

    def _require_class(self, session: Session, campaign_id: str, class_id: str, lock: bool = False) -> CampaignClassRow:
        row = self._load_class(session, campaign_id, class_id, lock)
        if row is None:
            raise UnknownClass(f"campaign {campaign_id} has no class {class_id}")
        return row
