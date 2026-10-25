"""WebSocketSessionManager: one (session, message processor) pair per connection."""

import pytest

from scenegems_tool.gateway.socket_message_processor import SocketMessageProcessor
from scenegems_tool.gateway.socket_session import SocketSession
from scenegems_tool.gateway.web_socket_session_manager import WebSocketSessionManager
from tests.scenegems_tool.gateway.conftest import FakeWebSocket, settle

pytestmark = pytest.mark.anyio


@pytest.fixture
async def manager():
    manager = WebSocketSessionManager()
    yield manager
    manager.shutdown_all()


async def test_create_session_returns_a_session_and_its_processor(manager, websocket):
    session, processor = manager.create_session(websocket)
    assert isinstance(session, SocketSession)
    assert isinstance(processor, SocketMessageProcessor)
    assert processor.session is session
    assert session.websocket is websocket


async def test_get_session_returns_the_existing_pair(manager, websocket):
    created = manager.create_session(websocket)
    assert manager.get_session(websocket) == created


async def test_get_session_creates_one_for_an_unknown_connection(manager, websocket):
    session, _ = manager.get_session(websocket)
    assert manager.get_session(websocket)[0] is session


async def test_connections_are_kept_apart(manager):
    first, second = FakeWebSocket(), FakeWebSocket()
    assert manager.create_session(first)[0] is not manager.create_session(second)[0]
    assert len(manager._sessions_by_connection) == 2


async def test_remove_session_cancels_both_and_forgets_the_connection(manager, websocket):
    session, processor = manager.create_session(websocket)
    manager.remove_session(websocket)
    await settle()
    assert session.outbound_task.cancelled()
    assert processor.worker_task.cancelled()
    assert manager._sessions_by_connection == {}


async def test_removing_an_unknown_connection_is_harmless(manager, websocket):
    manager.remove_session(websocket)
    assert manager._sessions_by_connection == {}


async def test_shutdown_all_cancels_everything(manager):
    pairs = [manager.create_session(FakeWebSocket()) for _ in range(3)]
    manager.shutdown_all()
    await settle()
    assert manager._sessions_by_connection == {}
    assert all(session.outbound_task.cancelled() and processor.worker_task.cancelled() for session, processor in pairs)
