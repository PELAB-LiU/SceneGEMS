import pytest

from tests.scenegems_tool.vessel_stack.stack_cases import CASE_NAMES, GeneratedStack, generate_stack


@pytest.fixture(scope="session")
def stacks() -> dict:
    """The three generated stacks of stack_cases, built once per session."""
    return {case: generate_stack(case) for case in CASE_NAMES}


@pytest.fixture(scope="session")
def gazebo_stack(stacks) -> GeneratedStack:
    return stacks["gazebo_lockstep_wind"]


@pytest.fixture(scope="session")
def ardupilot_sim_stack(stacks) -> GeneratedStack:
    return stacks["ardupilot_sim_lockstep"]


@pytest.fixture(scope="session")
def arduagent_stack(stacks) -> GeneratedStack:
    return stacks["ardupilot_sim_arduagent"]
