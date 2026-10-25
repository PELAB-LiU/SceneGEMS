"""Records of the artifacts in the master's artifact store and of who references them.

The artifact store (P4.3) keeps the files; these rows say what it holds and what still
needs each file. Retention removes references; the sweep deletes the files of artifacts
without references that have not been used for a while (stored again, referenced or
unreferenced), so a fresh upload survives until the engine references it.

Every method takes an optional session (see store_session).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Collection, List, Optional

from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.schema import ArtifactHolderKind, ArtifactReferenceRow, ArtifactRow
from scenegems_tool.persistence.schema.artifact_tables import require_sha256_hex
from scenegems_tool.persistence.stores.store_session import session_scope


class UnknownArtifact(LookupError):
    pass


class ArtifactMismatch(ValueError):
    """An artifact is stored again with another size than its record has: not the same content."""


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_hash: str
    kind: str
    size_bytes: int
    stored_size_bytes: Optional[int]
    media_type: str
    created_at: datetime
    last_used_at: datetime

    @classmethod
    def from_row(cls, row: ArtifactRow) -> "ArtifactRecord":
        return cls(
            artifact_hash=row.hash,
            kind=row.kind,
            size_bytes=row.size_bytes,
            stored_size_bytes=row.stored_size_bytes,
            media_type=row.media_type,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
        )


@dataclass(frozen=True)
class ArtifactInsert:
    artifact: ArtifactRecord
    created: bool  # False when the artifact was recorded already


@dataclass(frozen=True)
class ArtifactReference:
    artifact_hash: str
    holder_kind: ArtifactHolderKind
    holder_id: str
    role: str
    campaign_id: Optional[str]
    created_at: datetime

    @classmethod
    def from_row(cls, row: ArtifactReferenceRow) -> "ArtifactReference":
        return cls(artifact_hash=row.artifact_hash, holder_kind=row.holder_kind, holder_id=row.holder_id, role=row.role, campaign_id=row.campaign_id, created_at=row.created_at)


class ArtifactRecordStore:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock = utc_now):
        self._sessions = session_factory
        self._clock = clock

    # Artifacts

    def insert_if_absent(self, artifact_hash: str, kind: str, size_bytes: int, media_type: str, stored_size_bytes: Optional[int] = None, *, session: Optional[Session] = None) -> ArtifactInsert:
        """Records an artifact once; recording it again marks it as used now.

        A second record with another size raises ArtifactMismatch: one hash, one content.
        """
        require_sha256_hex(artifact_hash)
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            statement = (
                insert(ArtifactRow)
                .values(hash=artifact_hash, kind=kind, size_bytes=size_bytes, stored_size_bytes=stored_size_bytes, media_type=media_type, created_at=now, last_used_at=now)
                .on_conflict_do_nothing(index_elements=[ArtifactRow.hash])
                .returning(ArtifactRow.hash)
            )
            created = scope.execute(statement).scalar_one_or_none() is not None
            row = scope.execute(select(ArtifactRow).where(ArtifactRow.hash == artifact_hash).with_for_update(key_share=True).execution_options(populate_existing=True)).scalar_one()
            if not created:
                if row.size_bytes != size_bytes:
                    raise ArtifactMismatch(f"artifact {artifact_hash} has {row.size_bytes} bytes on record, not {size_bytes}")
                row.last_used_at = now
                scope.flush()
            return ArtifactInsert(artifact=ArtifactRecord.from_row(row), created=created)

    def get(self, artifact_hash: str, *, session: Optional[Session] = None) -> Optional[ArtifactRecord]:
        with session_scope(self._sessions, session) as scope:
            row = scope.get(ArtifactRow, artifact_hash, populate_existing=True)
            return None if row is None else ArtifactRecord.from_row(row)

    def list_unreferenced(self, unused_for_s: float, limit: Optional[int] = 100, *, session: Optional[Session] = None) -> List[ArtifactRecord]:
        """Artifacts without references, not used for unused_for_s seconds, least recently used first."""
        cutoff = self._clock() - timedelta(seconds=unused_for_s)
        with session_scope(self._sessions, session) as scope:
            query = select(ArtifactRow).where(self._unreferenced(), ArtifactRow.last_used_at <= cutoff).order_by(ArtifactRow.last_used_at, ArtifactRow.hash).limit(limit)
            return [ArtifactRecord.from_row(row) for row in scope.execute(query).scalars()]

    def delete_unreferenced(self, artifact_hashes: Collection[str], unused_for_s: float, *, session: Optional[Session] = None) -> List[str]:
        """Deletes the records among artifact_hashes that are still unreferenced and unused; returns their hashes, sorted.

        The sweep deletes a file only after its record is gone, so a record never points at
        a missing file. An artifact referenced or stored again since it was listed is kept.
        """
        if not artifact_hashes:
            return []
        cutoff = self._clock() - timedelta(seconds=unused_for_s)
        with session_scope(self._sessions, session) as scope:
            statement = (
                delete(ArtifactRow)
                .where(ArtifactRow.hash.in_(sorted(set(artifact_hashes))), self._unreferenced(), ArtifactRow.last_used_at <= cutoff)
                .returning(ArtifactRow.hash)
                .execution_options(synchronize_session=False)
            )
            return sorted(scope.execute(statement).scalars())

    # References

    def add_reference(self, artifact_hash: str, holder_kind: ArtifactHolderKind, holder_id: str, role: str, campaign_id: Optional[str] = None, *, session: Optional[Session] = None) -> bool:
        """Records that the holder needs the artifact in this role; False when it did already. Raises UnknownArtifact."""
        require_sha256_hex(artifact_hash)
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            # FOR NO KEY UPDATE: a concurrent delete of the record waits for this reference
            row = scope.execute(select(ArtifactRow).where(ArtifactRow.hash == artifact_hash).with_for_update(key_share=True).execution_options(populate_existing=True)).scalar_one_or_none()
            if row is None:
                raise UnknownArtifact(artifact_hash)
            statement = (
                insert(ArtifactReferenceRow)
                .values(artifact_hash=artifact_hash, holder_kind=holder_kind, holder_id=str(holder_id), role=role, campaign_id=campaign_id, created_at=now)
                .on_conflict_do_nothing(index_elements=[ArtifactReferenceRow.artifact_hash, ArtifactReferenceRow.holder_kind, ArtifactReferenceRow.holder_id, ArtifactReferenceRow.role])
                .returning(ArtifactReferenceRow.id)
            )
            created = scope.execute(statement).scalar_one_or_none() is not None
            row.last_used_at = now
            scope.flush()
            return created

    def remove_reference(self, artifact_hash: str, holder_kind: ArtifactHolderKind, holder_id: str, role: str, *, session: Optional[Session] = None) -> bool:
        """Removes one reference; False when there was none."""
        removed = self._remove(
            [ArtifactReferenceRow.artifact_hash == artifact_hash, ArtifactReferenceRow.holder_kind == holder_kind, ArtifactReferenceRow.holder_id == str(holder_id), ArtifactReferenceRow.role == role],
            session,
        )
        return bool(removed)

    def remove_references_of(self, holder_kind: ArtifactHolderKind, holder_id: str, roles: Optional[Collection[str]] = None, *, session: Optional[Session] = None) -> List[str]:
        """Removes the holder's references (in the given roles, or all); returns the hashes it referenced, sorted."""
        conditions = [ArtifactReferenceRow.holder_kind == holder_kind, ArtifactReferenceRow.holder_id == str(holder_id)]
        if roles is not None:
            conditions.append(ArtifactReferenceRow.role.in_(list(roles)))
        return self._remove(conditions, session)

    def references(self, artifact_hash: str, *, session: Optional[Session] = None) -> List[ArtifactReference]:
        with session_scope(self._sessions, session) as scope:
            query = select(ArtifactReferenceRow).where(ArtifactReferenceRow.artifact_hash == artifact_hash).order_by(ArtifactReferenceRow.id)
            return [ArtifactReference.from_row(row) for row in scope.execute(query).scalars()]

    def references_of(self, holder_kind: ArtifactHolderKind, holder_id: str, *, session: Optional[Session] = None) -> List[ArtifactReference]:
        with session_scope(self._sessions, session) as scope:
            query = select(ArtifactReferenceRow).where(ArtifactReferenceRow.holder_kind == holder_kind, ArtifactReferenceRow.holder_id == str(holder_id)).order_by(ArtifactReferenceRow.id)
            return [ArtifactReference.from_row(row) for row in scope.execute(query).scalars()]

    # Helpers

    @staticmethod
    def _unreferenced():
        return ~exists().where(ArtifactReferenceRow.artifact_hash == ArtifactRow.hash)

    def _remove(self, conditions, session: Optional[Session]) -> List[str]:
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            statement = delete(ArtifactReferenceRow).where(*conditions).returning(ArtifactReferenceRow.artifact_hash).execution_options(synchronize_session=False)
            hashes = sorted(set(scope.execute(statement).scalars()))
            if hashes:
                scope.execute(update(ArtifactRow).where(ArtifactRow.hash.in_(hashes)).values(last_used_at=now).execution_options(synchronize_session=False))
            return hashes
