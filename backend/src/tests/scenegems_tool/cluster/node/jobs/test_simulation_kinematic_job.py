"""simulation.kinematic in process: the live monitor gives the post-hoc result, and a run without it is unchanged."""

import pytest

from scenegems_tool.cluster.node.jobs import monitoring_post_hoc_job, simulation_kinematic_job
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_replay

SUMMARY_KEYS = ("scenes", "monitored_scenes", "time_step", "rules", "failed_rules", "passed")


def _quiet(message, progress=None):
    pass


@pytest.fixture
def simulate(make_job, head_on_trajectories):
    def simulate(**fields):
        return simulation_kinematic_job.execute(make_job(JobType.SIMULATION_KINEMATIC, {"trajectories": head_on_trajectories.to_dict(), **fields}), _quiet)

    return simulate


def test_a_run_without_a_monitor_is_the_plain_replay(simulate, head_on_trajectories):
    result = simulate()
    assert "monitor" not in result
    assert result["state_digest"] == run_kinematic_replay(head_on_trajectories).state_digest()
    assert result["steps"] == 120


def test_the_live_monitor_gives_the_post_hoc_result_of_the_same_run(simulate, make_job):
    plain, live = simulate(), simulate(monitor="live")
    assert live["state_digest"] == plain["state_digest"] and live["steps"] == plain["steps"]
    post_hoc = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"trajectories": plain["trajectories"]}), _quiet)
    assert {key: live["monitor"][key] for key in SUMMARY_KEYS} == {key: post_hoc[key] for key in SUMMARY_KEYS}
    assert live["monitor"]["stopped_early_at"] is None
    assert not live["monitor"]["passed"] and live["monitor"]["failed_rules"][0]["first_failed_at"] == 61


def test_early_stop_waits_while_any_rule_is_undecided(simulate):
    # Head on without evasion: two rules fail at 61 s, the vessels' manoeuvre rules stay undecided.
    result = simulate(monitor="live", early_stop=True)
    assert result["steps"] == 120 and result["monitor"]["stopped_early_at"] is None


def test_early_stop_ends_the_run_when_every_rule_is_decided(simulate, monkeypatch):
    monkeypatch.setattr(RuleOutcomes, "every_rule_decided", lambda outcomes: bool(outcomes.failed_rules()))
    stopped = simulate(monitor="live", early_stop=True)
    assert stopped["steps"] == 61 and stopped["run_record"]["steps"] == 61
    assert stopped["monitor"]["stopped_early_at"] == 61 and stopped["monitor"]["scenes"] == 62
    assert len(stopped["trajectories"]["scene_list"]) == 62
    assert stopped["state_digest"] == simulate(steps=61)["state_digest"]  # the same states as a run of that length


def test_a_stop_on_the_last_step_is_not_early(simulate, monkeypatch):
    monkeypatch.setattr(RuleOutcomes, "every_rule_decided", lambda outcomes: outcomes.monitored_scenes == 11)
    result = simulate(monitor="live", early_stop=True, steps=10)
    assert result["steps"] == 10 and result["monitor"]["stopped_early_at"] is None
