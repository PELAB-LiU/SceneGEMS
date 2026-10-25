import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from scenegems_tool.cluster.security.credentials.pairing_tokens import (
    DEFAULT_TOKEN_LIFETIME,
    PairingTokenRejected,
    consume_pairing_token,
    create_pairing_token,
    purge_expired_pairing_tokens,
)


def test_created_token_is_consumed_once(store, instant):
    created = create_pairing_token(store, now=instant)
    assert created.expires_at == instant + DEFAULT_TOKEN_LIFETIME
    record = consume_pairing_token(store, created.token, now=instant + timedelta(minutes=1))
    assert record.expires_at == created.expires_at
    with pytest.raises(PairingTokenRejected, match="already used"):
        consume_pairing_token(store, created.token, now=instant + timedelta(minutes=2))


def test_unknown_and_empty_tokens_are_rejected(store, instant):
    create_pairing_token(store, now=instant)
    for token in ["not-a-token", ""]:
        with pytest.raises(PairingTokenRejected):
            consume_pairing_token(store, token, now=instant)


def test_expired_token_is_rejected_and_used_up(store, instant):
    created = create_pairing_token(store, lifetime=timedelta(minutes=5), now=instant)
    with pytest.raises(PairingTokenRejected, match="expired"):
        consume_pairing_token(store, created.token, now=instant + timedelta(minutes=5))
    with pytest.raises(PairingTokenRejected, match="already used"):
        consume_pairing_token(store, created.token, now=instant)


def test_rejection_messages_never_contain_the_token(store, instant):
    created = create_pairing_token(store, lifetime=timedelta(minutes=5), now=instant)
    with pytest.raises(PairingTokenRejected) as rejected:
        consume_pairing_token(store, created.token, now=instant + timedelta(hours=1))
    assert created.token not in str(rejected.value)
    assert created.token not in repr(created)


def test_store_holds_only_the_token_hash(store, instant, tmp_path):
    created = create_pairing_token(store, note="lab-1", now=instant)
    files = list((tmp_path / "store").rglob("*.json"))
    assert len(files) == 1
    content = files[0].read_text()
    assert created.token not in content
    assert json.loads(content)["note"] == "lab-1"


@pytest.mark.parametrize("lifetime", [timedelta(0), timedelta(seconds=-1), timedelta(days=8)])
def test_lifetime_must_be_positive_and_bounded(store, lifetime):
    with pytest.raises(ValueError):
        create_pairing_token(store, lifetime=lifetime)


def test_concurrent_consumers_get_the_token_once(store, instant):
    created = create_pairing_token(store, now=instant)

    def attempt(_):
        try:
            consume_pairing_token(store, created.token, now=instant)
            return True
        except PairingTokenRejected:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(16)))
    assert results.count(True) == 1


def test_purge_removes_only_expired_tokens(store, instant):
    keep = create_pairing_token(store, lifetime=timedelta(hours=1), now=instant)
    create_pairing_token(store, lifetime=timedelta(minutes=1), now=instant)
    assert purge_expired_pairing_tokens(store, now=instant + timedelta(minutes=2)) == 1
    assert consume_pairing_token(store, keep.token, now=instant + timedelta(minutes=3))
