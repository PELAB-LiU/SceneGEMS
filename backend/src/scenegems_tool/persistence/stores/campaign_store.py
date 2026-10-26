"""Campaigns: creation with their first config and classes, states, config versions and events.

The operator sets the desired state; the pipeline engine converges the actual state to it
and records each step as a campaign event. A desired stop is final, and a campaign whose
actual state is final (stopped or completed) changes no more.

Every method takes an optional session (see store_session).
"""

from datetime import datetime
from typing import Any, Collection, Dict, List, Mapping, Optional, Sequence
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.schema import (
    CampaignActualState,
    CampaignClassRow,
    CampaignClassState,
    CampaignConfigVersionRow,
    CampaignDesiredState,
    CampaignEventKind,
    CampaignEventRow,
    CampaignRow,
)
from scenegems_tool.persistence.schema.artifact_tables import require_sha256_hex
from scenegems_tool.persistence.stores.campaign_records import CampaignEventRecord, CampaignRecord, ClassSpec, ConfigVersionRecord
from scenegems_tool.persistence.stores.store_session import session_scope


class UnknownCampaign(LookupError):
    pass


class CampaignStateConflict(ValueError):
    """The campaign is not in the state the caller expected, or the change is not allowed from it."""


class CampaignStore:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock = utc_now):
        self._sessions = session_factory
        self._clock = clock

    # Creation and queries

    def create_campaign(
        self,
        name: str,
        config: Dict[str, Any],
        config_hash: str,
        classes: Sequence[ClassSpec],
        pinned_fingerprints: Optional[Mapping[str, str]] = None,
        desired_state: CampaignDesiredState = CampaignDesiredState.PAUSED,
        *,
        session: Optional[Session] = None,
    ) -> CampaignRecord:
        """Creates a campaign with config version 1 and its classes, and records its creation.

        The config is the validated config as JSON and config_hash its sha256; the classes
        come resolved from the catalog with their content hashes. A new campaign is created
        (actual state); it waits paused unless desired_state says otherwise.
        """
        require_sha256_hex(config_hash)
        if not classes:
            raise ValueError("a campaign needs at least one class")
        class_ids = [spec.class_id for spec in classes]
        if len(set(class_ids)) != len(class_ids):
            raise ValueError(f"a class may appear once per campaign: {sorted({class_id for class_id in class_ids if class_ids.count(class_id) > 1})}")
        for spec in classes:
            require_sha256_hex(spec.content_hash)
        if desired_state == CampaignDesiredState.STOPPED:
            raise ValueError("a new campaign cannot start stopped")
        now = self._clock()
        campaign_id = str(uuid4())
        with session_scope(self._sessions, session) as scope:
            row = CampaignRow(
                id=campaign_id,
                name=name,
                desired_state=desired_state,
                actual_state=CampaignActualState.CREATED,
                config_version=1,
                pinned_fingerprints=dict(pinned_fingerprints or {}),
                created_at=now,
                updated_at=now,
            )
            scope.add(row)
            scope.flush()
            scope.add(CampaignConfigVersionRow(campaign_id=campaign_id, version=1, config=config, config_hash=config_hash, created_at=now))
            scope.add_all(
                CampaignClassRow(
                    campaign_id=campaign_id,
                    class_id=spec.class_id,
                    content_hash=spec.content_hash,
                    vessel_count=spec.vessel_count,
                    obstacle_count=spec.obstacle_count,
                    quota=spec.quota,
                    failure_budget=spec.failure_budget,
                    complete_count=0,
                    dropped_count=0,
                    in_flight_count=0,
                    state=CampaignClassState.OPEN,
                    created_at=now,
                    updated_at=now,
                )
                for spec in classes
            )
            self._append(scope, campaign_id, CampaignEventKind.CREATED, now, {"config_hash": config_hash, "classes": len(classes), "desired_state": desired_state.value})
            scope.flush()
            return CampaignRecord.from_row(row)

    def get_campaign(self, campaign_id: str, *, lock: bool = False, session: Optional[Session] = None) -> Optional[CampaignRecord]:
        """The campaign, or None. lock takes its row for the rest of the caller's transaction."""
        with session_scope(self._sessions, session) as scope:
            row = self._load(scope, campaign_id, lock)
            return None if row is None else CampaignRecord.from_row(row)

    def list_campaigns(
        self, actual_states: Optional[Collection[CampaignActualState]] = None, limit: Optional[int] = 100, offset: int = 0, *, session: Optional[Session] = None
    ) -> List[CampaignRecord]:
        """Campaigns, newest first, optionally only those in the given actual states."""
        with session_scope(self._sessions, session) as scope:
            query = select(CampaignRow).order_by(CampaignRow.created_at.desc(), CampaignRow.id).offset(offset).limit(limit)
            if actual_states is not None:
                query = query.where(CampaignRow.actual_state.in_(list(actual_states)))
            return [CampaignRecord.from_row(row) for row in scope.execute(query).scalars()]

    def count_campaigns(self, actual_states: Optional[Collection[CampaignActualState]] = None, *, session: Optional[Session] = None) -> int:
        """How many campaigns list_campaigns would return for the same filter without a page."""
        with session_scope(self._sessions, session) as scope:
            query = select(func.count()).select_from(CampaignRow)
            if actual_states is not None:
                query = query.where(CampaignRow.actual_state.in_(list(actual_states)))
            return scope.execute(query).scalar_one()

    def unfinished_campaigns(self, *, session: Optional[Session] = None) -> List[CampaignRecord]:
        """Campaigns the engine still works on (actual state not final), oldest first."""
        with session_scope(self._sessions, session) as scope:
            query = select(CampaignRow).where(CampaignRow.actual_state.notin_([state for state in CampaignActualState if state.is_final])).order_by(CampaignRow.created_at, CampaignRow.id)
            return [CampaignRecord.from_row(row) for row in scope.execute(query).scalars()]

    def config_version(self, campaign_id: str, version: Optional[int] = None, *, session: Optional[Session] = None) -> Optional[ConfigVersionRecord]:
        """A config version of the campaign; its current one when version is None."""
        with session_scope(self._sessions, session) as scope:
            if version is None:
                campaign = self._load(scope, campaign_id)
                if campaign is None:
                    return None
                version = campaign.config_version
            row = scope.get(CampaignConfigVersionRow, (campaign_id, version))
            return None if row is None else ConfigVersionRecord.from_row(row)

    def config_versions(self, campaign_id: str, *, session: Optional[Session] = None) -> List[ConfigVersionRecord]:
        with session_scope(self._sessions, session) as scope:
            query = select(CampaignConfigVersionRow).where(CampaignConfigVersionRow.campaign_id == campaign_id).order_by(CampaignConfigVersionRow.version)
            return [ConfigVersionRecord.from_row(row) for row in scope.execute(query).scalars()]

    # States

    def set_desired_state(self, campaign_id: str, state: CampaignDesiredState, expected: Optional[CampaignDesiredState] = None, *, session: Optional[Session] = None) -> CampaignRecord:
        """The operator's control: sets the desired state and records it as an event.

        Setting the state it already has changes nothing. Raises CampaignStateConflict when
        expected is given and differs, when the campaign was asked to stop already, or when
        it is finished.
        """
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            row = self._require(scope, campaign_id, lock=True)
            if expected is not None and row.desired_state != expected:
                raise CampaignStateConflict(f"campaign {campaign_id} wants {row.desired_state.value}, not {expected.value}")
            if row.desired_state == state:
                return CampaignRecord.from_row(row)
            if row.actual_state.is_final:
                raise CampaignStateConflict(f"campaign {campaign_id} is {row.actual_state.value}")
            if row.desired_state == CampaignDesiredState.STOPPED:
                raise CampaignStateConflict(f"campaign {campaign_id} is stopping; a stop cannot be undone")
            previous = row.desired_state
            row.desired_state = state
            row.updated_at = now
            self._append(scope, campaign_id, CampaignEventKind.DESIRED_STATE_CHANGED, now, {"from": previous.value, "to": state.value})
            scope.flush()
            return CampaignRecord.from_row(row)

    def set_actual_state(
        self,
        campaign_id: str,
        state: CampaignActualState,
        reason: Optional[str] = None,
        expected: Optional[CampaignActualState] = None,
        *,
        session: Optional[Session] = None,
    ) -> CampaignRecord:
        """The engine's report of where the campaign is; the engine appends the matching event itself.

        The first running state sets started_at, a final state finished_at. reason
        replaces the state reason (None clears it). Raises CampaignStateConflict when
        expected is given and differs, or when the campaign is finished already.
        """
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            row = self._require(scope, campaign_id, lock=True)
            if expected is not None and row.actual_state != expected:
                raise CampaignStateConflict(f"campaign {campaign_id} is {row.actual_state.value}, not {expected.value}")
            if row.actual_state.is_final and row.actual_state != state:
                raise CampaignStateConflict(f"campaign {campaign_id} is {row.actual_state.value}")
            row.actual_state = state
            row.state_reason = reason
            row.updated_at = now
            if state == CampaignActualState.RUNNING and row.started_at is None:
                row.started_at = now
            if state.is_final and row.finished_at is None:
                row.finished_at = now
            scope.flush()
            return CampaignRecord.from_row(row)

    # Events

    def append_event(
        self, campaign_id: str, kind: CampaignEventKind, detail: Optional[Dict[str, Any]] = None, class_id: Optional[str] = None, *, session: Optional[Session] = None
    ) -> CampaignEventRecord:
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            self._require(scope, campaign_id)
            row = self._append(scope, campaign_id, kind, now, detail, class_id)
            scope.flush()
            return CampaignEventRecord.from_row(row)

    def list_events(
        self,
        campaign_id: str,
        after_event_id: int = 0,
        limit: Optional[int] = 100,
        kinds: Optional[Collection[CampaignEventKind]] = None,
        *,
        session: Optional[Session] = None,
    ) -> List[CampaignEventRecord]:
        """The campaign's events in order, after after_event_id (for paging), optionally of some kinds."""
        with session_scope(self._sessions, session) as scope:
            query = select(CampaignEventRow).where(CampaignEventRow.campaign_id == campaign_id, CampaignEventRow.id > after_event_id).order_by(CampaignEventRow.id).limit(limit)
            if kinds is not None:
                query = query.where(CampaignEventRow.kind.in_(list(kinds)))
            return [CampaignEventRecord.from_row(row) for row in scope.execute(query).scalars()]

    def count_events(self, campaign_id: str, after_event_id: int = 0, kinds: Optional[Collection[CampaignEventKind]] = None, *, session: Optional[Session] = None) -> int:
        """How many events list_events would return for the same filters without a limit."""
        with session_scope(self._sessions, session) as scope:
            query = select(func.count()).select_from(CampaignEventRow).where(CampaignEventRow.campaign_id == campaign_id, CampaignEventRow.id > after_event_id)
            if kinds is not None:
                query = query.where(CampaignEventRow.kind.in_(list(kinds)))
            return scope.execute(query).scalar_one()

    # Helpers

    @staticmethod
    def _append(session: Session, campaign_id: str, kind: CampaignEventKind, at: datetime, detail: Optional[Dict[str, Any]] = None, class_id: Optional[str] = None) -> CampaignEventRow:
        row = CampaignEventRow(campaign_id=campaign_id, at=at, kind=kind, class_id=class_id, detail=detail or {})
        session.add(row)
        return row

    @staticmethod
    def _load(session: Session, campaign_id: str, lock: bool = False) -> Optional[CampaignRow]:
        query = select(CampaignRow).where(CampaignRow.id == campaign_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update(key_share=True)  # FOR NO KEY UPDATE: cases and events referencing it are not blocked
        return session.execute(query).scalar_one_or_none()

    def _require(self, session: Session, campaign_id: str, lock: bool = False) -> CampaignRow:
        row = self._load(session, campaign_id, lock)
        if row is None:
            raise UnknownCampaign(campaign_id)
        return row
