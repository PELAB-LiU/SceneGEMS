from sqlalchemy.dialects import postgresql

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.stores.job_claim import free_job_types, next_queued_job_query

SCENE = JobType.SCENE_GENERATION
TRAJECTORY = JobType.TRAJECTORY_GENERATION
KINEMATIC = JobType.SIMULATION_KINEMATIC


def test_free_job_types_need_a_free_slot():
    slots = {SCENE: 2, TRAJECTORY: 1, KINEMATIC: 4}
    assert free_job_types(slots, {SCENE: 2, TRAJECTORY: 0, KINEMATIC: 3}) == [TRAJECTORY, KINEMATIC]


def test_free_job_types_ignore_leases_of_types_the_node_does_not_offer():
    assert free_job_types({SCENE: 1}, {KINEMATIC: 5}) == [SCENE]


def test_free_job_types_can_be_limited():
    assert free_job_types({SCENE: 1, TRAJECTORY: 1}, {}, only=[TRAJECTORY]) == [TRAJECTORY]
    assert free_job_types({SCENE: 1}, {}, only=[KINEMATIC]) == []


def _compiled_query() -> str:
    query = next_queued_job_query([SCENE], {"site": "lab"}, {"scenegems-scenario-generation": "f1"}, free_memory_mb=4000, cpus=4.0)
    return str(query.compile(dialect=postgresql.dialect()))


def test_claim_query_skips_locked_rows():
    sql = _compiled_query()
    assert sql.rstrip().endswith("LIMIT %(param_1)s FOR UPDATE SKIP LOCKED")


def test_claim_query_orders_by_priority_then_submission():
    assert "ORDER BY job.priority DESC, job.submitted_at, job.seq" in _compiled_query()


def test_claim_query_filters_in_sql():
    sql = _compiled_query()
    assert "job.state = %(state_1)s" in sql
    assert "job.job_type IN" in sql
    assert "job.required_labels <@ %(required_labels_1)s::JSONB" in sql
    assert "job.required_fingerprints <@ %(required_fingerprints_1)s::JSONB" in sql
    assert "job.min_memory_mb <= %(min_memory_mb_1)s" in sql
    assert "job.min_cpus <= %(min_cpus_1)s" in sql
