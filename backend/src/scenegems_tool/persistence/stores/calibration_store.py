"""Calibration results: the measured deviation of a stack on a release and an environment.

A result is keyed by its stack, fingerprints and environment (JSON objects, compared by
their canonical JSON hash) and its reference scenario. A newer measurement of the same key
replaces the older one. A verdict on a bounded stack is sensitive while no result exists
for its stack, fingerprints and environment.

Every method takes an optional session (see store_session).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.persistence.canonical_json import canonical_json_sha256
from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.schema import CalibrationResultRow
from scenegems_tool.persistence.stores.store_session import session_scope


@dataclass(frozen=True)
class NewCalibrationResult:
    stack: Dict[str, Any]
    fingerprints: Dict[str, str]
    environment: Dict[str, Any]
    reference_scenario: str
    repeats: int
    exact: bool
    deviation_bound_m: Optional[float] = None
    envelope: Optional[Dict[str, Any]] = None  # the deviation envelope as the calibration job reports it
    campaign_id: Optional[str] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class CalibrationResult:
    calibration_id: int
    stack: Dict[str, Any]
    fingerprints: Dict[str, str]
    environment: Dict[str, Any]
    reference_scenario: str
    repeats: int
    exact: bool
    deviation_bound_m: Optional[float]
    envelope: Dict[str, Any]
    campaign_id: Optional[str]
    note: Optional[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: CalibrationResultRow) -> "CalibrationResult":
        return cls(
            calibration_id=row.id,
            stack=dict(row.stack),
            fingerprints=dict(row.fingerprints),
            environment=dict(row.environment),
            reference_scenario=row.reference_scenario,
            repeats=row.repeats,
            exact=row.exact,
            deviation_bound_m=row.deviation_bound_m,
            envelope=dict(row.envelope),
            campaign_id=row.campaign_id,
            note=row.note,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class CalibrationStore:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock = utc_now):
        self._sessions = session_factory
        self._clock = clock

    def upsert(self, result: NewCalibrationResult, *, session: Optional[Session] = None) -> CalibrationResult:
        """Stores the result, replacing an earlier one of the same stack, fingerprints, environment and reference scenario."""
        if result.repeats < 1:
            raise ValueError(f"a calibration needs at least one repeat, got {result.repeats}")
        now = self._clock()
        measured = dict(
            repeats=result.repeats,
            exact=result.exact,
            deviation_bound_m=result.deviation_bound_m,
            envelope=dict(result.envelope or {}),
            campaign_id=result.campaign_id,
            note=result.note,
            updated_at=now,
        )
        with session_scope(self._sessions, session) as scope:
            statement = (
                insert(CalibrationResultRow)
                .values(
                    stack=result.stack,
                    stack_hash=canonical_json_sha256(result.stack),
                    fingerprints=result.fingerprints,
                    fingerprints_hash=canonical_json_sha256(result.fingerprints),
                    environment=result.environment,
                    environment_hash=canonical_json_sha256(result.environment),
                    reference_scenario=result.reference_scenario,
                    created_at=now,
                    **measured,
                )
                .on_conflict_do_update(constraint="uq_calibration_result_key", set_=measured)
                .returning(CalibrationResultRow.id)
            )
            row_id = scope.execute(statement).scalar_one()
            return CalibrationResult.from_row(scope.get(CalibrationResultRow, row_id, populate_existing=True))

    def find(
        self,
        stack: Mapping[str, Any],
        fingerprints: Mapping[str, str],
        environment: Optional[Mapping[str, Any]] = None,
        reference_scenario: Optional[str] = None,
        *,
        session: Optional[Session] = None,
    ) -> List[CalibrationResult]:
        """Results for the stack on these fingerprints, optionally for one environment and reference scenario."""
        with session_scope(self._sessions, session) as scope:
            query = select(CalibrationResultRow).where(
                CalibrationResultRow.stack_hash == canonical_json_sha256(dict(stack)), CalibrationResultRow.fingerprints_hash == canonical_json_sha256(dict(fingerprints))
            )
            if environment is not None:
                query = query.where(CalibrationResultRow.environment_hash == canonical_json_sha256(dict(environment)))
            if reference_scenario is not None:
                query = query.where(CalibrationResultRow.reference_scenario == reference_scenario)
            query = query.order_by(CalibrationResultRow.reference_scenario, CalibrationResultRow.id).execution_options(populate_existing=True)
            return [CalibrationResult.from_row(row) for row in scope.execute(query).scalars()]

    def list_results(self, limit: Optional[int] = 100, offset: int = 0, *, session: Optional[Session] = None) -> List[CalibrationResult]:
        with session_scope(self._sessions, session) as scope:
            query = select(CalibrationResultRow).order_by(CalibrationResultRow.updated_at.desc(), CalibrationResultRow.id).offset(offset).limit(limit)
            return [CalibrationResult.from_row(row) for row in scope.execute(query).scalars()]
