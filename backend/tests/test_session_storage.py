"""Unit tests for SessionStorage."""

from unittest.mock import Mock, patch

from deerflow.agents.memory.session_storage import (
    SessionStorage,
    create_empty_session_memory,
    get_session_storage,
    set_session_storage,
    set_session_store_factory,
)


class TestCreateEmptySessionMemory:
    """Tests for create_empty_session_memory()."""

    def test_returns_valid_structure(self):
        """Empty session memory has required fields."""
        memory = create_empty_session_memory()

        assert "version" in memory
        assert "lastUpdated" in memory
        assert "session_context" in memory
        assert "facts" in memory

        assert memory["version"] == "1.0"
        assert memory["session_context"]["summary"] == ""
        assert memory["session_context"]["updatedAt"] == ""
        assert memory["facts"] == []

    def test_last_updated_is_iso_format(self):
        """lastUpdated field is ISO 8601 format."""
        memory = create_empty_session_memory()

        # Should be ISO format with Z suffix
        assert memory["lastUpdated"].endswith("Z")
        assert "T" in memory["lastUpdated"]


class TestSessionStorage:
    """Tests for SessionStorage class."""

    def test_namespace_construction(self):
        """_ns() constructs correct namespace tuple."""
        mock_factory = Mock()
        storage = SessionStorage(mock_factory)

        with patch('deerflow.agents.memory.session_storage.get_current_tenant_id', return_value='tenant_123'):
            ns = storage._ns('thread_abc', user_id='user_xyz')

        assert ns == ('memory_session', 'tenant_123', 'user_xyz', 'thread_abc')

    def test_namespace_with_empty_user_id(self):
        """_ns() handles None user_id as empty string."""
        mock_factory = Mock()
        storage = SessionStorage(mock_factory)

        with patch('deerflow.agents.memory.session_storage.get_current_tenant_id', return_value='tenant_123'):
            ns = storage._ns('thread_abc', user_id=None)

        assert ns == ('memory_session', 'tenant_123', '', 'thread_abc')

    def test_load_returns_empty_when_not_found(self):
        """load() returns empty session memory when item not found."""
        mock_store = Mock()
        mock_store.aget = Mock(return_value=Mock(__await__=lambda self: iter([None])))
        mock_factory = Mock(return_value=mock_store)

        storage = SessionStorage(mock_factory)

        with patch('deerflow.agents.memory.session_storage._run_async', return_value=None):
            result = storage.load('thread_abc', user_id='user_xyz')

        assert result['version'] == '1.0'
        assert result['facts'] == []

    def test_load_returns_stored_data(self):
        """load() returns stored session memory data."""
        stored_data = {
            'version': '1.0',
            'lastUpdated': '2026-05-26T10:00:00Z',
            'session_context': {'summary': 'Debugging auth issue', 'updatedAt': '2026-05-26T10:00:00Z'},
            'facts': [
                {'id': 'fact_1', 'content': 'JWT token expires after 1 hour', 'confidence': 0.85}
            ]
        }

        mock_store = Mock()
        mock_item = Mock()
        mock_item.value = stored_data
        mock_factory = Mock(return_value=mock_store)

        storage = SessionStorage(mock_factory)

        with patch('deerflow.agents.memory.session_storage._run_async', return_value=mock_item):
            result = storage.load('thread_abc', user_id='user_xyz')

        assert result == stored_data

    def test_save_persists_to_store(self):
        """save() persists session memory to Store."""
        memory_data = {
            'version': '1.0',
            'session_context': {'summary': 'Test', 'updatedAt': ''},
            'facts': []
        }

        mock_store = Mock()
        mock_store.aput = Mock(return_value=Mock(__await__=lambda self: iter([True])))
        mock_factory = Mock(return_value=mock_store)

        storage = SessionStorage(mock_factory)

        with patch('deerflow.agents.memory.session_storage._run_async', return_value=True):
            with patch('deerflow.agents.memory.session_storage.get_current_tenant_id', return_value='tenant_123'):
                result = storage.save(memory_data, 'thread_abc', user_id='user_xyz')

        assert result is True
        mock_store.aput.assert_called_once()

    def test_save_updates_last_updated_timestamp(self):
        """save() updates lastUpdated field before persisting."""
        memory_data = {
            'version': '1.0',
            'lastUpdated': '2026-01-01T00:00:00Z',
            'session_context': {'summary': '', 'updatedAt': ''},
            'facts': []
        }

        mock_store = Mock()
        mock_store.aput = Mock(return_value=Mock(__await__=lambda self: iter([True])))
        mock_factory = Mock(return_value=mock_store)

        storage = SessionStorage(mock_factory)

        with patch('deerflow.agents.memory.session_storage._run_async', return_value=True):
            with patch('deerflow.agents.memory.session_storage.get_current_tenant_id', return_value='tenant_123'):
                storage.save(memory_data, 'thread_abc', user_id='user_xyz')

        # Check that aput was called with updated lastUpdated
        call_args = mock_store.aput.call_args
        saved_data = call_args[0][2]  # Third positional arg is the data
        assert saved_data['lastUpdated'] != '2026-01-01T00:00:00Z'
        assert saved_data['lastUpdated'].endswith('Z')

    def test_reload_delegates_to_load(self):
        """reload() calls load() with same arguments."""
        mock_factory = Mock()
        storage = SessionStorage(mock_factory)

        with patch.object(storage, 'load', return_value={'version': '1.0'}) as mock_load:
            result = storage.reload('thread_abc', user_id='user_xyz')

        mock_load.assert_called_once_with('thread_abc', user_id='user_xyz')
        assert result == {'version': '1.0'}

    def test_load_handles_exception_gracefully(self):
        """load() returns empty memory on exception."""
        mock_factory = Mock(side_effect=RuntimeError("Store unavailable"))
        storage = SessionStorage(mock_factory)

        result = storage.load('thread_abc', user_id='user_xyz')

        assert result['version'] == '1.0'
        assert result['facts'] == []

    def test_save_handles_exception_gracefully(self):
        """save() returns False on exception."""
        memory_data = {'version': '1.0', 'facts': []}
        mock_factory = Mock(side_effect=RuntimeError("Store unavailable"))
        storage = SessionStorage(mock_factory)

        result = storage.save(memory_data, 'thread_abc', user_id='user_xyz')

        assert result is False


class TestSessionStorageSingleton:
    """Tests for session storage singleton management."""

    def setup_method(self):
        """Reset singleton before each test."""
        set_session_storage(None)

    def test_get_session_storage_returns_none_for_file_backend(self):
        """get_session_storage() returns None when using FileMemoryStorage."""
        from deerflow.agents.memory.storage import FileMemoryStorage

        with patch('deerflow.agents.memory.storage.get_memory_storage', return_value=FileMemoryStorage()):
            result = get_session_storage()

        assert result is None

    def test_get_session_storage_returns_instance_for_store_backend(self):
        """get_session_storage() returns SessionStorage when using StoreMemoryStorage."""
        from deerflow.agents.memory.storage import StoreMemoryStorage

        mock_store_storage = StoreMemoryStorage(Mock())

        with patch('deerflow.agents.memory.storage.get_memory_storage', return_value=mock_store_storage):
            result = get_session_storage()

        assert isinstance(result, SessionStorage)

    def test_set_session_storage_overrides_singleton(self):
        """set_session_storage() overrides the singleton instance."""
        mock_storage = Mock(spec=SessionStorage)

        set_session_storage(mock_storage)
        result = get_session_storage()

        # Should return the mock even though we haven't set up StoreMemoryStorage
        assert result is mock_storage

    def test_set_session_store_factory_resets_singleton(self):
        """set_session_store_factory() resets singleton to use new factory."""
        # First call creates singleton with factory1
        factory1 = Mock()
        set_session_store_factory(factory1)

        # Second call should reset singleton
        factory2 = Mock()
        set_session_store_factory(factory2)

        # Next get_session_storage() should use factory2
        from deerflow.agents.memory.storage import StoreMemoryStorage
        mock_store_storage = StoreMemoryStorage(factory2)

        with patch('deerflow.agents.memory.storage.get_memory_storage', return_value=mock_store_storage):
            result = get_session_storage()

        assert isinstance(result, SessionStorage)

    def test_tenant_isolation_via_namespace(self):
        """Different tenants get different namespaces."""
        mock_factory = Mock()
        storage = SessionStorage(mock_factory)

        with patch('deerflow.agents.memory.session_storage.get_current_tenant_id', side_effect=['tenant_A', 'tenant_B']):
            ns_a = storage._ns('thread_1', user_id='user_1')
            ns_b = storage._ns('thread_1', user_id='user_1')

        assert ns_a[1] == 'tenant_A'
        assert ns_b[1] == 'tenant_B'
        assert ns_a != ns_b
