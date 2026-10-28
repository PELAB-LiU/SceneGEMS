"""Retention: which references a case and its runs lose once its verdicts of every step exist, or when it is cancelled."""

from types import SimpleNamespace

from scenegems_tool.assurance.campaign.campaign_config import RetentionPolicy
from scenegems_tool.assurance.pipeline import retention
from scenegems_tool.persistence.schema import ArtifactHolderKind, StepKind, VerdictState

PASSED, FAILED, UNMONITORED = VerdictState.PASSED, VerdictState.FAILED, VerdictState.UNMONITORED
CASE, RUN = ArtifactHolderKind.CASE, ArtifactHolderKind.RUN


class _Artifacts:
    """Records what retention removes, holder by holder."""

    def __init__(self):
        self.removed = {}

    def remove_references_of(self, holder_kind, holder_id, roles=None, *, session=None):
        self.removed.setdefault((holder_kind, holder_id), set()).update(roles)
        return [f"{holder_id}:{role}" for role in roles]


def _apply(policy, runs=None, steps=None, keep_trajectories=False):
    artifacts = _Artifacts()
    runs = runs or {}
    retention.apply_on_verdicts(SimpleNamespace(artifacts=artifacts), None, policy, 7, runs, {run_index: [10 + run_index] for run_index in runs}, steps, keep_trajectories)
    return artifacts.removed


def test_everything_stays_under_all():
    assert _apply(RetentionPolicy.ALL, {0: PASSED}, {StepKind.SCENE: PASSED}) == {}


def test_verdicts_only_drops_every_log_the_trajectories_and_the_monitors_frames():
    removed = _apply(RetentionPolicy.VERDICTS_ONLY, {0: FAILED}, {StepKind.SCENE: FAILED})
    assert removed == {(RUN, "10"): {"state_log", "frames"}, (CASE, "7"): {"trajectory_data", "scene_frames", "trajectory_frames"}}


def test_failures_keeps_what_a_failed_verdict_of_any_step_judged():
    removed = _apply(RetentionPolicy.FAILURES, {0: PASSED, 1: UNMONITORED}, {StepKind.SCENE: FAILED, StepKind.TRAJECTORIES: PASSED})
    # the scene's failure keeps the case's trajectories and the scene monitor's frames
    assert removed == {(RUN, "10"): {"state_log", "frames"}, (RUN, "11"): {"state_log", "frames"}, (CASE, "7"): {"trajectory_frames"}}


def test_failures_drops_the_trajectories_of_a_case_without_a_failed_verdict():
    removed = _apply(RetentionPolicy.FAILURES, {0: FAILED}, {StepKind.TRAJECTORIES: PASSED})
    assert removed == {(CASE, "7"): {"scene_frames", "trajectory_frames"}}  # run 0 failed: its log and the trajectories stay
    removed = _apply(RetentionPolicy.FAILURES, {}, {StepKind.SCENE: PASSED})
    assert removed == {(CASE, "7"): {"scene_frames", "trajectory_frames", "trajectory_data"}}


def test_the_trajectories_of_a_trajectory_campaign_stay_as_its_output():
    assert _apply(RetentionPolicy.FAILURES, {}, {StepKind.TRAJECTORIES: PASSED}, keep_trajectories=True) == {(CASE, "7"): {"scene_frames", "trajectory_frames"}}
    assert _apply(RetentionPolicy.VERDICTS_ONLY, {}, {}, keep_trajectories=True) == {(CASE, "7"): {"scene_frames", "trajectory_frames"}}


def test_a_cancelled_case_keeps_nothing_judged_later():
    artifacts = _Artifacts()
    retention.apply_on_cancel(SimpleNamespace(artifacts=artifacts), None, RetentionPolicy.FAILURES, 7, [12])
    assert artifacts.removed == {(RUN, "12"): {"state_log", "frames"}, (CASE, "7"): {"trajectory_data", "scene_frames", "trajectory_frames"}}
    assert retention.apply_on_cancel(SimpleNamespace(artifacts=_Artifacts()), None, RetentionPolicy.ALL, 7, [12]) == []
