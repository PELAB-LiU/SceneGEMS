from pathlib import Path

import pytest

from tests.snapshots import SnapshotChecker


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--update-snapshots", action="store_true", default=False, help="rewrite the snapshot files under data/ folders with the generated output")


@pytest.fixture
def snapshot(request: pytest.FixtureRequest) -> SnapshotChecker:
    """Snapshots of the requesting test live in the data/ folder next to its file."""
    return SnapshotChecker(Path(request.path).parent / "data", update=bool(request.config.getoption("--update-snapshots")))
