"""Retention: which artifact references a case keeps once its verdicts exist.

    all             (the default) every reference stays
    failures        the generated trajectories, the state logs and the monitors' frames stay
                    only for failed verdicts: a passed or unmonitored run loses its state log
                    (and frames), a scene or trajectory verdict that did not fail loses its
                    frames, and a case without a failed verdict of any step loses its
                    generated trajectories
    verdicts_only   every run loses its state log, and the case its generated trajectories and
                    the frames of its scene and trajectory monitors

The scene stays in every policy, and so do the trajectories of a campaign whose last step is
trajectory generation, since they are its output. Frames exist only when the campaign keeps them
(policy.keep_frames) and follow what they judged. Cases that end without verdicts keep
everything, except cancelled ones under failures and verdicts_only, whose outputs were never
judged. Only references are removed here; the artifact sweep deletes the files nothing
references any more. Run records and cases keep the hashes they recorded.
"""

from typing import Iterable, List, Mapping, Optional

from sqlalchemy.orm import Session

from scenegems_tool.assurance.campaign.campaign_config import RetentionPolicy
from scenegems_tool.assurance.pipeline.verdicts import CASE_TRAJECTORY_ROLES, RUN_LOG_ROLES, STEP_FRAME_ROLES
from scenegems_tool.persistence.schema import ArtifactHolderKind, StepKind, VerdictState
from scenegems_tool.persistence.stores import AssuranceStores


def _remove(stores: AssuranceStores, session: Session, case_id: int, run_record_ids: Iterable[int], case_roles: Iterable[str]) -> List[str]:
    removed: List[str] = []
    for run_record_id in run_record_ids:
        removed += stores.artifacts.remove_references_of(ArtifactHolderKind.RUN, str(run_record_id), RUN_LOG_ROLES, session=session)
    case_roles = tuple(case_roles)
    if case_roles:
        removed += stores.artifacts.remove_references_of(ArtifactHolderKind.CASE, str(case_id), case_roles, session=session)
    return sorted(set(removed))


def apply_on_verdicts(
    stores: AssuranceStores,
    session: Session,
    policy: RetentionPolicy,
    case_id: int,
    verdict_states: Mapping[int, VerdictState],
    run_records: Mapping[int, List[int]],
    step_states: Optional[Mapping[StepKind, VerdictState]] = None,
    keep_trajectories: bool = False,
) -> List[str]:
    """Applies the policy to a case whose verdicts were just written; returns the hashes whose references it removed.

    verdict_states maps each run index to its verdict, run_records each run index to the
    run record ids of its repeats, step_states each monitored scene or trajectory step to
    its verdict. keep_trajectories keeps the generated trajectories in every policy (they are
    the output of a campaign whose last step is trajectory generation).
    """
    step_states = step_states or {}
    trajectory_roles = () if keep_trajectories else CASE_TRAJECTORY_ROLES
    if policy == RetentionPolicy.ALL:
        return []
    if policy == RetentionPolicy.VERDICTS_ONLY:
        released = [run_record_id for ids in run_records.values() for run_record_id in ids]
        return _remove(stores, session, case_id, released, trajectory_roles + tuple(STEP_FRAME_ROLES.values()))
    released = [run_record_id for run_index, ids in run_records.items() if verdict_states.get(run_index) != VerdictState.FAILED for run_record_id in ids]
    any_failed = any(state == VerdictState.FAILED for state in list(verdict_states.values()) + list(step_states.values()))
    case_roles = [role for step, role in STEP_FRAME_ROLES.items() if step_states.get(step) != VerdictState.FAILED]
    if not any_failed:
        case_roles += trajectory_roles
    return _remove(stores, session, case_id, released, case_roles)


def apply_on_cancel(stores: AssuranceStores, session: Session, policy: RetentionPolicy, case_id: int, run_record_ids: Iterable[int]) -> List[str]:
    """A cancelled case under failures or verdicts_only keeps nothing of its runs, its generated trajectories and its monitors' frames."""
    if policy == RetentionPolicy.ALL:
        return []
    return _remove(stores, session, case_id, run_record_ids, CASE_TRAJECTORY_ROLES + tuple(STEP_FRAME_ROLES.values()))
