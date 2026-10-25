"""Retention: which artifact references a case keeps once its verdicts exist.

    all             (the default) every reference stays
    failures        the generated trajectories and the state logs stay only for failed verdicts:
                    a passed or unmonitored run loses its state log (and frames), and a case
                    without a failed verdict loses its generated trajectories
    verdicts_only   every run loses its state log and the case its generated trajectories

The scene stays in every policy. Frames exist only when the campaign keeps them
(policy.keep_frames) and follow the state log. Cases that end without verdicts keep
everything, except cancelled ones under failures and verdicts_only, whose runs were never
judged. Only references are removed here; the artifact sweep deletes the files nothing
references any more. Run records and cases keep the hashes they recorded.
"""

from typing import Iterable, List, Mapping

from sqlalchemy.orm import Session

from scenegems_tool.assurance.campaign.campaign_config import RetentionPolicy
from scenegems_tool.assurance.pipeline.verdicts import CASE_TRAJECTORY_ROLES, RUN_LOG_ROLES
from scenegems_tool.persistence.schema import ArtifactHolderKind, VerdictState
from scenegems_tool.persistence.stores import AssuranceStores


def _remove(stores: AssuranceStores, session: Session, case_id: int, run_record_ids: Iterable[int], drop_case_trajectories: bool) -> List[str]:
    removed: List[str] = []
    for run_record_id in run_record_ids:
        removed += stores.artifacts.remove_references_of(ArtifactHolderKind.RUN, str(run_record_id), RUN_LOG_ROLES, session=session)
    if drop_case_trajectories:
        removed += stores.artifacts.remove_references_of(ArtifactHolderKind.CASE, str(case_id), CASE_TRAJECTORY_ROLES, session=session)
    return sorted(set(removed))


def apply_on_verdicts(stores: AssuranceStores, session: Session, policy: RetentionPolicy, case_id: int, verdict_states: Mapping[int, VerdictState], run_records: Mapping[int, List[int]]) -> List[str]:
    """Applies the policy to a case whose verdicts were just written; returns the hashes whose references it removed.

    verdict_states maps each run index to its verdict, run_records each run index to the
    run record ids of its repeats.
    """
    if policy == RetentionPolicy.ALL:
        return []
    if policy == RetentionPolicy.VERDICTS_ONLY:
        released = [run_record_id for ids in run_records.values() for run_record_id in ids]
        return _remove(stores, session, case_id, released, drop_case_trajectories=True)
    released = [run_record_id for run_index, ids in run_records.items() if verdict_states.get(run_index) != VerdictState.FAILED for run_record_id in ids]
    any_failed = any(state == VerdictState.FAILED for state in verdict_states.values())
    return _remove(stores, session, case_id, released, drop_case_trajectories=not any_failed)


def apply_on_cancel(stores: AssuranceStores, session: Session, policy: RetentionPolicy, case_id: int, run_record_ids: Iterable[int]) -> List[str]:
    """A cancelled case under failures or verdicts_only keeps nothing of its runs and generated trajectories."""
    if policy == RetentionPolicy.ALL:
        return []
    return _remove(stores, session, case_id, run_record_ids, drop_case_trajectories=True)
