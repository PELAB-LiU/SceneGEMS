"""Run records and verdicts of the cases, and the coverage summary per class.

Writes are idempotent per key, so the engine may process an event twice: a second run
record for the same case, run and repeat, or a second verdict for the same case and run,
returns the stored one unchanged. The campaign and class of a result are copied from its
case, for the API's queries.

Every method takes an optional session (see store_session).
"""

from typing import Any, List, Optional, Tuple, Type

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.schema import CampaignClassRow, MonitorImplementation, RunRecordRow, ScenarioCaseRow, VerdictRow, VerdictState
from scenegems_tool.persistence.schema.artifact_tables import require_sha256_hex
from scenegems_tool.persistence.stores.case_store import UnknownCase
from scenegems_tool.persistence.stores.result_records import ClassCoverage, NewRunRecord, NewVerdict, RunRecord, VerdictRecord
from scenegems_tool.persistence.stores.store_session import session_scope


def check_verdict(verdict: NewVerdict) -> None:
    """The rules the table's constraints hold, with a readable message before the database refuses."""
    if (verdict.state == VerdictState.UNMONITORED) != (verdict.monitor == MonitorImplementation.EMPTY):
        raise ValueError(f"a verdict is unmonitored exactly when its monitor is empty, got {verdict.state.value} from {verdict.monitor.value}")
    if verdict.early_stop_time_s is not None and verdict.monitor != MonitorImplementation.LIVE:
        raise ValueError("only the live monitor stops a run early")
    if verdict.first_failure_time_s is not None and verdict.state != VerdictState.FAILED:
        raise ValueError("a first failure time belongs to a failed verdict")
    if verdict.state == VerdictState.PASSED and verdict.failed_rules:
        raise ValueError(f"a passed verdict has no failed rules, got {list(verdict.failed_rules)}")


class ResultStore:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock = utc_now):
        self._sessions = session_factory
        self._clock = clock

    # Run records

    def add_run_record(self, record: NewRunRecord, *, session: Optional[Session] = None) -> RunRecord:
        for artifact_hash in record.artifacts.values():
            require_sha256_hex(artifact_hash)
        values = dict(record.__dict__)
        with session_scope(self._sessions, session) as scope:
            campaign_id, class_id = self._case_of(scope, record.case_id)
            row_id = self._insert_once(scope, RunRecordRow, ["case_id", "run_index", "repeat_index"], dict(values, campaign_id=campaign_id, class_id=class_id, created_at=self._clock()))
            row = scope.get(RunRecordRow, row_id) if row_id is not None else self._run_record_row(scope, record.case_id, record.run_index, record.repeat_index)
            return RunRecord.from_row(row, self._case_index(scope, row.case_id))

    def get_run_record(self, run_record_id: int, *, session: Optional[Session] = None) -> Optional[RunRecord]:
        with session_scope(self._sessions, session) as scope:
            row = scope.get(RunRecordRow, run_record_id)
            return None if row is None else RunRecord.from_row(row, self._case_index(scope, row.case_id))

    def list_run_records(
        self,
        campaign_id: str,
        class_id: Optional[str] = None,
        case_id: Optional[int] = None,
        run_index: Optional[int] = None,
        limit: Optional[int] = 100,
        offset: int = 0,
        *,
        session: Optional[Session] = None,
    ) -> List[RunRecord]:
        """Run records of the campaign ordered by class, case, run and repeat, each with its case index."""
        with session_scope(self._sessions, session) as scope:
            query = self._filtered(
                select(RunRecordRow, ScenarioCaseRow.case_index).join(ScenarioCaseRow, ScenarioCaseRow.id == RunRecordRow.case_id), RunRecordRow, campaign_id, class_id, case_id, run_index
            )
            query = query.order_by(RunRecordRow.class_id, ScenarioCaseRow.case_index, RunRecordRow.run_index, RunRecordRow.repeat_index).offset(offset).limit(limit)
            return [RunRecord.from_row(row, case_index) for row, case_index in scope.execute(query)]

    def count_run_records(self, campaign_id: str, class_id: Optional[str] = None, case_id: Optional[int] = None, run_index: Optional[int] = None, *, session: Optional[Session] = None) -> int:
        """How many run records list_run_records would return for the same filters without a page."""
        with session_scope(self._sessions, session) as scope:
            return scope.execute(self._filtered(select(func.count()).select_from(RunRecordRow), RunRecordRow, campaign_id, class_id, case_id, run_index)).scalar_one()

    # Verdicts

    def add_verdict(self, verdict: NewVerdict, *, session: Optional[Session] = None) -> VerdictRecord:
        check_verdict(verdict)
        values = dict(verdict.__dict__, failed_rules=list(verdict.failed_rules))
        with session_scope(self._sessions, session) as scope:
            campaign_id, class_id = self._case_of(scope, verdict.case_id)
            row_id = self._insert_once(scope, VerdictRow, ["case_id", "run_index"], dict(values, campaign_id=campaign_id, class_id=class_id, created_at=self._clock()))
            if row_id is None:
                row = scope.execute(select(VerdictRow).where(VerdictRow.case_id == verdict.case_id, VerdictRow.run_index == verdict.run_index)).scalar_one()
            else:
                row = scope.get(VerdictRow, row_id)
            return VerdictRecord.from_row(row, self._case_index(scope, row.case_id))

    def list_verdicts(
        self,
        campaign_id: str,
        class_id: Optional[str] = None,
        case_id: Optional[int] = None,
        state: Optional[VerdictState] = None,
        run_index: Optional[int] = None,
        sensitive: Optional[bool] = None,
        limit: Optional[int] = 100,
        offset: int = 0,
        *,
        session: Optional[Session] = None,
    ) -> List[VerdictRecord]:
        """Verdicts of the campaign ordered by class, case and run, each with its case index; filter on class, case, state (passed or failed), run, sensitivity."""
        with session_scope(self._sessions, session) as scope:
            query = select(VerdictRow, ScenarioCaseRow.case_index).join(ScenarioCaseRow, ScenarioCaseRow.id == VerdictRow.case_id)
            query = self._verdict_filtered(query, campaign_id, class_id, case_id, state, run_index, sensitive)
            query = query.order_by(VerdictRow.class_id, ScenarioCaseRow.case_index, VerdictRow.run_index).offset(offset).limit(limit)
            return [VerdictRecord.from_row(row, case_index) for row, case_index in scope.execute(query)]

    def count_verdicts(
        self,
        campaign_id: str,
        state: Optional[VerdictState] = None,
        *,
        class_id: Optional[str] = None,
        case_id: Optional[int] = None,
        run_index: Optional[int] = None,
        sensitive: Optional[bool] = None,
        session: Optional[Session] = None,
    ) -> int:
        """How many verdicts list_verdicts would return for the same filters without a page."""
        with session_scope(self._sessions, session) as scope:
            query = self._verdict_filtered(select(func.count()).select_from(VerdictRow), campaign_id, class_id, case_id, state, run_index, sensitive)
            return scope.execute(query).scalar_one()

    # Coverage

    def coverage(self, campaign_id: str, *, session: Optional[Session] = None) -> List[ClassCoverage]:
        """Per class of the campaign, ordered by class id: state, quota, case counts and verdicts per run and state."""
        with session_scope(self._sessions, session) as scope:
            classes = (
                scope.execute(select(CampaignClassRow).where(CampaignClassRow.campaign_id == campaign_id).order_by(CampaignClassRow.class_id).execution_options(populate_existing=True)).scalars().all()
            )
            verdicts = {row.class_id: {} for row in classes}
            query = (
                select(VerdictRow.class_id, VerdictRow.run_index, VerdictRow.state, func.count())
                .where(VerdictRow.campaign_id == campaign_id)
                .group_by(VerdictRow.class_id, VerdictRow.run_index, VerdictRow.state)
            )
            for class_id, run_index, state, count in scope.execute(query):
                verdicts[class_id].setdefault(run_index, {})[state] = count
            return [
                ClassCoverage(
                    class_id=row.class_id,
                    state=row.state,
                    quota=row.quota,
                    failure_budget=row.failure_budget,
                    complete=row.complete_count,
                    dropped=row.dropped_count,
                    in_flight=row.in_flight_count,
                    verdicts={run_index: dict(states) for run_index, states in sorted(verdicts[row.class_id].items())},
                )
                for row in classes
            ]

    # Helpers

    @staticmethod
    def _case_of(session: Session, case_id: int) -> Tuple[str, str]:
        found = session.execute(select(ScenarioCaseRow.campaign_id, ScenarioCaseRow.class_id).where(ScenarioCaseRow.id == case_id)).first()
        if found is None:
            raise UnknownCase(case_id)
        return found[0], found[1]

    @staticmethod
    def _case_index(session: Session, case_id: int) -> Optional[int]:
        return session.execute(select(ScenarioCaseRow.case_index).where(ScenarioCaseRow.id == case_id)).scalar_one_or_none()

    @classmethod
    def _verdict_filtered(cls, query, campaign_id: str, class_id: Optional[str], case_id: Optional[int], state: Optional[VerdictState], run_index: Optional[int], sensitive: Optional[bool]):
        query = cls._filtered(query, VerdictRow, campaign_id, class_id, case_id, run_index)
        if state is not None:
            query = query.where(VerdictRow.state == state)
        if sensitive is not None:
            query = query.where(VerdictRow.sensitive.is_(sensitive))
        return query

    @staticmethod
    def _insert_once(session: Session, table: Type[Any], key: List[str], values: dict) -> Optional[int]:
        statement = insert(table).values(**values).on_conflict_do_nothing(index_elements=[getattr(table, column) for column in key]).returning(table.id)
        return session.execute(statement).scalar_one_or_none()

    @staticmethod
    def _run_record_row(session: Session, case_id: int, run_index: int, repeat_index: int) -> RunRecordRow:
        query = select(RunRecordRow).where(RunRecordRow.case_id == case_id, RunRecordRow.run_index == run_index, RunRecordRow.repeat_index == repeat_index)
        return session.execute(query).scalar_one()

    @staticmethod
    def _filtered(query, table, campaign_id: str, class_id: Optional[str], case_id: Optional[int], run_index: Optional[int]):
        query = query.where(table.campaign_id == campaign_id)
        if class_id is not None:
            query = query.where(table.class_id == class_id)
        if case_id is not None:
            query = query.where(table.case_id == case_id)
        if run_index is not None:
            query = query.where(table.run_index == run_index)
        return query
