import pytest

from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.schema import Base, JobEventRow, JobRow, NodeCapabilityRow, NodeRow


def _check_constraint(table, name):
    return next(constraint for constraint in table.constraints if constraint.name == name)


def test_tables():
    assert set(Base.metadata.tables) == {"node", "node_capability", "node_fingerprint", "job", "job_event"}


@pytest.mark.parametrize(
    "table, column, values",
    [
        (JobRow.__table__, "job_type", [job_type.value for job_type in JobType]),
        (JobRow.__table__, "state", [state.value for state in JobState]),
        (NodeCapabilityRow.__table__, "job_type", [job_type.value for job_type in JobType]),
        (JobEventRow.__table__, "to_state", [state.value for state in JobState]),
    ],
)
def test_enum_columns_store_values(table, column, values):
    assert table.c[column].type.enums == values


def test_enum_constraints_follow_the_naming_convention():
    names = {constraint.name for constraint in JobRow.__table__.constraints}
    assert {"ck_job_job_type", "ck_job_state", "pk_job", "uq_job_idempotency_key", "uq_job_lease_id", "fk_job_lease_owner_node"} <= names
    assert "ck_node_status" in {constraint.name for constraint in NodeRow.__table__.constraints}


def test_idempotency_key_is_unique_and_required():
    column = JobRow.__table__.c.idempotency_key
    assert column.unique and not column.nullable


def test_queue_index_covers_queued_jobs_in_claim_order():
    index = next(index for index in JobRow.__table__.indexes if index.name == "ix_job_queue_order")
    assert str(index.dialect_options["postgresql"]["where"]) == "state = 'queued'"
    assert [str(expression) for expression in index.expressions] == ["priority DESC", "job.submitted_at", "job.seq"]


def test_lease_columns_are_optional_and_owner_references_a_node():
    table = JobRow.__table__
    assert all(table.c[name].nullable for name in ("lease_id", "lease_owner", "lease_expires_at"))
    assert {foreign_key.target_fullname for foreign_key in table.c.lease_owner.foreign_keys} == {"node.id"}


def test_active_lease_must_be_complete():
    constraint = _check_constraint(JobRow.__table__, "ck_job_active_lease_complete")
    assert "lease_expires_at IS NOT NULL" in str(constraint.sqltext)


def test_node_children_are_deleted_with_the_node():
    for table_name in ("node_capability", "node_fingerprint"):
        (foreign_key,) = Base.metadata.tables[table_name].c.node_id.foreign_keys
        assert foreign_key.ondelete == "CASCADE"
