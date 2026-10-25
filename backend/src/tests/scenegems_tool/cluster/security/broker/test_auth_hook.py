import asyncio
from urllib.parse import urlencode

import pytest

from scenegems_tool.cluster.security.broker.auth_hook import AUTH_HOOK_PATH, create_broker_auth_app
from scenegems_tool.cluster.security.credentials.broker_accounts import create_node_broker_account

HOOK_SECRET = "test-hook-secret-0123456789abcdefghij"


def _post(app, body: bytes, headers: dict, path: str = AUTH_HOOK_PATH) -> int:
    """Call the ASGI app once, the way NanoMQ posts its login form, and return the status."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "client": ("172.18.0.5", 40000),
        "server": ("master-api", 8090),
    }
    messages = [{"type": "http.request", "body": body, "more_body": False}]
    status = {}

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            status["code"] = message["status"]

    asyncio.run(app(scope, receive, send))
    return status["code"]


@pytest.fixture
def account(store):
    return create_node_broker_account(store, "lab-1-a1b2c3")


@pytest.fixture
def app(store):
    return create_broker_auth_app(store, HOOK_SECRET)


def _form(username, password):
    return urlencode({"clientid": "c1", "username": username, "password": password}).encode()


AUTHORIZED = {"content-type": "application/x-www-form-urlencoded", "authorization": f"Bearer {HOOK_SECRET}"}


def test_valid_login_is_accepted(app, account):
    assert _post(app, _form(account.username, account.password), AUTHORIZED) == 200


def test_wrong_password_and_missing_fields_are_refused(app, account):
    assert _post(app, _form(account.username, "wrong"), AUTHORIZED) == 401
    assert _post(app, b"clientid=c1", AUTHORIZED) == 401


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-secret", f"Basic {HOOK_SECRET}", HOOK_SECRET])
def test_requests_without_the_hook_secret_are_refused_even_with_valid_logins(app, account, authorization):
    headers = {"content-type": "application/x-www-form-urlencoded"}
    if authorization is not None:
        headers["authorization"] = authorization
    assert _post(app, _form(account.username, account.password), headers) == 401


def test_oversized_forms_are_refused(app, account):
    assert _post(app, _form(account.username, account.password) + b"&x=" + b"a" * 5000, AUTHORIZED) == 413


def test_only_the_hook_path_is_served(app, account):
    assert _post(app, _form(account.username, account.password), AUTHORIZED, path="/docs") == 404
