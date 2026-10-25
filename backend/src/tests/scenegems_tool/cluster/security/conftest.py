from datetime import datetime, timezone

import pytest

from scenegems_tool.cluster.security.broker.broker_config import ClusterBrokerSettings
from scenegems_tool.cluster.security.master_security import MasterSecurity, initialize_master_security
from scenegems_tool.cluster.security.store.file_security_store import FileSecurityStore

# Test values only; generated secrets are never fixed in tests.
MASTER_ID = "lab-master"
MASTER_USERNAME = "master"
MASTER_PASSWORD = "test-master-password-0001"
HOOK_SECRET = "test-hook-secret-0123456789abcdefghij"


@pytest.fixture
def instant() -> datetime:
    return datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path) -> FileSecurityStore:
    return FileSecurityStore(tmp_path / "store")


def make_master_security(root, *, hook_url: str = "http://master-api:8090/cluster/broker/auth", addresses=("192.168.1.10", "master.lan")) -> MasterSecurity:
    return initialize_master_security(
        root,
        master_id=MASTER_ID,
        addresses=list(addresses),
        master_broker_username=MASTER_USERNAME,
        master_broker_password=MASTER_PASSWORD,
        broker=ClusterBrokerSettings(auth_hook_url=hook_url, auth_hook_secret=HOOK_SECRET),
    )


@pytest.fixture
def master_security(tmp_path) -> MasterSecurity:
    return make_master_security(tmp_path / "security")
