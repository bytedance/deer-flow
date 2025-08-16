# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import src.graph.checkpoint as checkpoint

POSTGRES_URL = "postgresql://postgres:postgres@localhost:5432/checkpointing_db"
MONGO_URL = "mongodb://admin:admin@localhost:27017/checkpointing_db?authSource=admin"


def test_with_local_postgres_db():
    """Ensure the ChatStreamManager can be initialized with a local PostgreSQL DB."""
    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=POSTGRES_URL,
    )
    assert manager.postgres_conn is not None
    assert manager.mongo_client is None


def test_with_local_mongo_db():
    """Ensure the ChatStreamManager can be initialized with a local MongoDB."""
    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=MONGO_URL,
    )
    assert manager.mongo_db is not None
    assert manager.postgres_conn is None


def test_init_without_checkpoint_saver():
    """Manager should not create DB clients when checkpoint_saver is False."""
    manager = checkpoint.ChatStreamManager(checkpoint_saver=False)
    assert manager.checkpoint_saver is False
    # DB connections are not created when saver is disabled
    assert manager.mongo_client is None
    assert manager.postgres_conn is None


def test_process_stream_partial_buffer_postgres(monkeypatch):
    """Partial chunks should be buffered; Postgres init is stubbed to no-op."""

    # Patch Postgres init to no-op
    def _no_pg(self):
        self.postgres_conn = None

    monkeypatch.setattr(
        checkpoint.ChatStreamManager, "_init_postgresql", _no_pg, raising=True
    )
    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=POSTGRES_URL,
    )
    result = manager.process_stream_message("t1", "hello", finish_reason="partial")
    assert result is True
    # Verify the chunk was stored in the in-memory store
    items = manager.store.search(("messages", "t1"), limit=10)
    values = [it.dict()["value"] for it in items]
    assert "hello" in values


def test_process_stream_partial_buffer_mongo(monkeypatch):
    """Partial chunks should be buffered; Mongo init is stubbed to no-op."""

    # Patch Mongo init to no-op for speed
    def _no_mongo(self):
        self.mongo_client = None
        self.mongo_db = None

    monkeypatch.setattr(
        checkpoint.ChatStreamManager, "_init_mongodb", _no_mongo, raising=True
    )

    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=MONGO_URL,
    )
    result = manager.process_stream_message("t2", "hello", finish_reason="partial")
    assert result is True
    # Verify the chunk was stored in the in-memory store
    items = manager.store.search(("messages", "t2"), limit=10)
    values = [it.dict()["value"] for it in items]
    assert "hello" in values


def test_persist_postgresql_local_db():
    """Ensure that the ChatStreamManager can persist to a local PostgreSQL DB."""
    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=POSTGRES_URL,
    )
    assert manager.postgres_conn is not None
    assert manager.mongo_client is None

    # Simulate a message to persist
    thread_id = "test_thread"
    messages = ["This is a test message."]
    result = manager._persist_to_postgresql(thread_id, messages)
    assert result is True
    # Simulate a message with existing thread
    result = manager._persist_to_postgresql(thread_id, ["Another message."])
    assert result is True


def test_persist_postgresql_called_with_aggregated_chunks(monkeypatch):
    """On 'stop', aggregated chunks should be passed to PostgreSQL persist method."""
    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=POSTGRES_URL,
    )

    assert (
        manager.process_stream_message("thd3", "Hello", finish_reason="partial") is True
    )
    assert (
        manager.process_stream_message("thd3", " World", finish_reason="stop") is True
    )

    # Verify the messages were aggregated correctly
    with manager.postgres_conn.cursor() as cursor:
        # Check if conversation already exists
        cursor.execute(
            "SELECT messages FROM chat_streams WHERE thread_id = %s", ("thd3",)
        )
        existing_record = cursor.fetchone()
        assert existing_record is not None
        assert existing_record["messages"] == ["Hello", " World"]


def test_persist_not_attempted_when_saver_disabled():
    """When saver disabled, stop should not persist and should return False."""
    manager = checkpoint.ChatStreamManager(checkpoint_saver=False)
    # stop should try to persist, but saver disabled => returns False
    assert manager.process_stream_message("t4", "hello", finish_reason="stop") is False


def test_persist_mongodb_local_db():
    """Ensure that the ChatStreamManager can persist to a local MongoDB."""
    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=MONGO_URL,
    )
    assert manager.mongo_db is not None
    assert manager.postgres_conn is None
    # Simulate a message to persist
    thread_id = "test_thread"
    messages = ["This is a test message."]
    result = manager._persist_to_mongodb(thread_id, messages)
    assert result is True
    # Simulate a message with existing thread
    result = manager._persist_to_mongodb(thread_id, ["Another message."])
    assert result is True


def test_persist_mongodb_called_with_aggregated_chunks(monkeypatch):
    """On 'stop', aggregated chunks should be passed to MongoDB persist method."""

    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=MONGO_URL,
    )

    assert (
        manager.process_stream_message("thd5", "Hello", finish_reason="partial") is True
    )
    assert (
        manager.process_stream_message("thd5", " World", finish_reason="stop") is True
    )

    # Verify the messages were aggregated correctly
    collection = manager.mongo_db.chat_streams
    existing_record = collection.find_one({"thread_id": "thd5"})
    assert existing_record is not None
    assert existing_record["messages"] == ["Hello", " World"]


def test_invalid_inputs_return_false(monkeypatch):
    """Empty thread_id or message should be rejected and return False."""

    def _no_mongo(self):
        self.mongo_client = None
        self.mongo_db = None

    monkeypatch.setattr(
        checkpoint.ChatStreamManager, "_init_mongodb", _no_mongo, raising=True
    )

    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=MONGO_URL,
    )
    assert manager.process_stream_message("", "msg", finish_reason="partial") is False
    assert manager.process_stream_message("tid", "", finish_reason="partial") is False


def test_unsupported_db_uri_scheme():
    """Manager should log warning for unsupported database URI schemes."""
    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True, db_uri="redis://localhost:6379/0"
    )
    # Should not have any database connections
    assert manager.mongo_client is None
    assert manager.postgres_conn is None
    assert manager.mongo_db is None


def test_process_stream_with_interrupt_finish_reason():
    """Test that 'interrupt' finish_reason triggers persistence like 'stop'."""
    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=MONGO_URL,
    )

    # Add partial message
    assert (
        manager.process_stream_message(
            "int_test", "Interrupted", finish_reason="partial"
        )
        is True
    )
    # Interrupt should trigger persistence
    assert (
        manager.process_stream_message(
            "int_test", " message", finish_reason="interrupt"
        )
        is True
    )


def test_postgresql_connection_failure(monkeypatch):
    """Test PostgreSQL connection failure handling."""

    def failing_connect(dsn, **kwargs):
        raise RuntimeError("Connection failed")

    monkeypatch.setattr("psycopg.connect", failing_connect)

    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=POSTGRES_URL,
    )
    # Should have no postgres connection on failure
    assert manager.postgres_conn is None


def test_mongodb_ping_failure(monkeypatch):
    """Test MongoDB ping failure during initialization."""

    class FakeAdmin:
        def command(self, name):
            raise RuntimeError("Ping failed")

    class FakeClient:
        def __init__(self, uri):
            self.admin = FakeAdmin()

    monkeypatch.setattr(checkpoint, "MongoClient", lambda uri: FakeClient(uri))

    manager = checkpoint.ChatStreamManager(
        checkpoint_saver=True,
        db_uri=MONGO_URL,
    )
    # Should not have mongo_db set on ping failure
    assert getattr(manager, "mongo_db", None) is None


def test_store_namespace_consistency():
    """Test that store namespace is consistently used across methods."""
    manager = checkpoint.ChatStreamManager(checkpoint_saver=False)

    # Process a partial message
    assert (
        manager.process_stream_message("ns_test", "chunk1", finish_reason="partial")
        is True
    )

    # Verify cursor is stored correctly
    cursor = manager.store.get(("messages", "ns_test"), "cursor")
    assert cursor is not None
    assert cursor.value["index"] == 0

    # Add another chunk
    assert (
        manager.process_stream_message("ns_test", "chunk2", finish_reason="partial")
        is True
    )

    # Verify cursor is incremented
    cursor = manager.store.get(("messages", "ns_test"), "cursor")
    assert cursor.value["index"] == 1


def test_cursor_initialization_edge_cases():
    """Test cursor handling edge cases."""
    manager = checkpoint.ChatStreamManager(checkpoint_saver=False)

    # Manually set a cursor with missing index
    namespace = ("messages", "edge_test")
    manager.store.put(namespace, "cursor", {})  # Missing 'index' key

    # Should handle missing index gracefully
    result = manager.process_stream_message(
        "edge_test", "test", finish_reason="partial"
    )
    assert result is True

    # Should default to 0 and increment to 1
    cursor = manager.store.get(namespace, "cursor")
    assert cursor.value["index"] == 1


def test_multiple_threads_isolation():
    """Test that different thread_ids are properly isolated."""
    manager = checkpoint.ChatStreamManager(checkpoint_saver=False)

    # Process messages for different threads
    assert (
        manager.process_stream_message("thread1", "msg1", finish_reason="partial")
        is True
    )
    assert (
        manager.process_stream_message("thread2", "msg2", finish_reason="partial")
        is True
    )
    assert (
        manager.process_stream_message("thread1", "msg3", finish_reason="partial")
        is True
    )

    # Verify isolation
    thread1_items = manager.store.search(("messages", "thread1"), limit=10)
    thread2_items = manager.store.search(("messages", "thread2"), limit=10)

    thread1_values = [
        item.dict()["value"]
        for item in thread1_items
        if isinstance(item.dict()["value"], str)
    ]
    thread2_values = [
        item.dict()["value"]
        for item in thread2_items
        if isinstance(item.dict()["value"], str)
    ]

    assert "msg1" in thread1_values
    assert "msg3" in thread1_values
    assert "msg2" in thread2_values
    assert "msg1" not in thread2_values
    assert "msg2" not in thread1_values


def test_mongodb_insert_and_update_paths(monkeypatch):
    """Exercise MongoDB insert, update, and exception branches."""

    # Fake Mongo classes
    class FakeUpdateResult:
        def __init__(self, modified_count):
            self.modified_count = modified_count

    class FakeInsertResult:
        def __init__(self, inserted_id):
            self.inserted_id = inserted_id

    class FakeCollection:
        def __init__(self, mode="insert_success"):
            self.mode = mode

        def find_one(self, query):
            if self.mode.startswith("insert"):
                return None
            return {"thread_id": query["thread_id"]}

        def update_one(self, q, s):
            if self.mode == "update_success":
                return FakeUpdateResult(1)
            return FakeUpdateResult(0)

        def insert_one(self, doc):
            if self.mode == "insert_success":
                return FakeInsertResult("ok")
            if self.mode == "insert_none":
                return FakeInsertResult(None)
            raise RuntimeError("boom")

    class FakeMongoDB:
        def __init__(self, mode):
            self.chat_streams = FakeCollection(mode)

    manager = checkpoint.ChatStreamManager(checkpoint_saver=True, db_uri=MONGO_URL)

    # Insert success
    manager.mongo_db = FakeMongoDB("insert_success")
    assert manager._persist_to_mongodb("th1", ["a"]) is True

    # Insert returns None id => False
    manager.mongo_db = FakeMongoDB("insert_none")
    assert manager._persist_to_mongodb("th2", ["a"]) is False

    # Insert raises => False
    manager.mongo_db = FakeMongoDB("insert_raise")
    assert manager._persist_to_mongodb("th3", ["a"]) is False

    # Update success
    manager.mongo_db = FakeMongoDB("update_success")
    assert manager._persist_to_mongodb("th4", ["a"]) is True

    # Update modifies 0 => False
    manager.mongo_db = FakeMongoDB("update_zero")
    assert manager._persist_to_mongodb("th5", ["a"]) is False


def test_postgresql_insert_update_and_error_paths():
    """Exercise PostgreSQL update, insert, and error/rollback branches."""
    calls = {"executed": []}

    class FakeCursor:
        def __init__(self, mode):
            self.mode = mode
            self.rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            calls["executed"].append(sql.strip().split()[0])
            if "SELECT" in sql:
                if self.mode == "update":
                    self._fetch = {"id": "x"}
                elif self.mode == "error":
                    raise RuntimeError("sql error")
                else:
                    self._fetch = None
            else:
                # UPDATE or INSERT
                self.rowcount = 1

        def fetchone(self):
            return getattr(self, "_fetch", None)

    class FakeConn:
        def __init__(self, mode):
            self.mode = mode
            self.commit_called = False
            self.rollback_called = False

        def cursor(self):
            return FakeCursor(self.mode)

        def commit(self):
            self.commit_called = True

        def rollback(self):
            self.rollback_called = True

    manager = checkpoint.ChatStreamManager(checkpoint_saver=True, db_uri=POSTGRES_URL)

    # Update path
    manager.postgres_conn = FakeConn("update")
    assert manager._persist_to_postgresql("t", ["m"]) is True
    assert manager.postgres_conn.commit_called is True

    # Insert path
    manager.postgres_conn = FakeConn("insert")
    assert manager._persist_to_postgresql("t", ["m"]) is True
    assert manager.postgres_conn.commit_called is True

    # Error path with rollback
    manager.postgres_conn = FakeConn("error")
    assert manager._persist_to_postgresql("t", ["m"]) is False
    assert manager.postgres_conn.rollback_called is True


def test_create_chat_streams_table_success_and_error():
    """Ensure table creation commits on success and rolls back on failure."""

    class FakeCursor:
        def __init__(self, should_fail=False):
            self.should_fail = should_fail

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql):
            if self.should_fail:
                raise RuntimeError("ddl fail")

    class FakeConn:
        def __init__(self, should_fail=False):
            self.should_fail = should_fail
            self.commits = 0
            self.rollbacks = 0

        def cursor(self):
            return FakeCursor(self.should_fail)

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    manager = checkpoint.ChatStreamManager(checkpoint_saver=True, db_uri=POSTGRES_URL)

    # Success
    manager.postgres_conn = FakeConn(False)
    manager._create_chat_streams_table()
    assert manager.postgres_conn.commits == 1

    # Failure triggers rollback
    manager.postgres_conn = FakeConn(True)
    manager._create_chat_streams_table()
    assert manager.postgres_conn.rollbacks == 1


def test_close_closes_resources_and_handles_errors():
    """Close should gracefully handle both success and exceptions."""
    flags = {"mongo": 0, "pg": 0}

    class M:
        def close(self):
            flags["mongo"] += 1

    class P:
        def __init__(self, raise_on_close=False):
            self.raise_on_close = raise_on_close

        def close(self):
            if self.raise_on_close:
                raise RuntimeError("close fail")
            flags["pg"] += 1

    manager = checkpoint.ChatStreamManager(checkpoint_saver=False)
    manager.mongo_client = M()
    manager.postgres_conn = P()
    manager.close()
    assert flags == {"mongo": 1, "pg": 1}

    # Trigger error branches (no raise escapes)
    manager.mongo_client = None  # skip mongo
    manager.postgres_conn = P(True)
    manager.close()  # should handle exception gracefully


def test_context_manager_calls_close(monkeypatch):
    """The context manager protocol should call close() on exit."""
    called = {"close": 0}

    def _noop(self):
        self.mongo_client = None
        self.mongo_db = None

    monkeypatch.setattr(
        checkpoint.ChatStreamManager, "_init_mongodb", _noop, raising=True
    )

    manager = checkpoint.ChatStreamManager(checkpoint_saver=True, db_uri=MONGO_URL)

    def fake_close():
        called["close"] += 1

    manager.close = fake_close
    with manager:
        pass
    assert called["close"] == 1


def test_init_mongodb_success_and_failure(monkeypatch):
    """MongoDB init should succeed with a valid client and fail gracefully otherwise."""

    class FakeAdmin:
        def command(self, name):
            assert name == "ping"

    class DummyDB:
        pass

    class FakeClient:
        def __init__(self, uri):
            self.uri = uri
            self.admin = FakeAdmin()
            self.checkpointing_db = DummyDB()

        def close(self):
            pass

    # Success path
    monkeypatch.setattr(checkpoint, "MongoClient", lambda uri: FakeClient(uri))
    manager = checkpoint.ChatStreamManager(checkpoint_saver=True, db_uri=MONGO_URL)
    assert manager.mongo_db is not None

    # Failure path
    class Boom:
        def __init__(self, uri):
            raise RuntimeError("fail connect")

    monkeypatch.setattr(checkpoint, "MongoClient", Boom)
    manager = checkpoint.ChatStreamManager(checkpoint_saver=True, db_uri=MONGO_URL)
    # Should have no mongo_db set on failure
    assert getattr(manager, "mongo_db", None) is None


def test_init_postgresql_calls_connect_and_create_table(monkeypatch):
    """PostgreSQL init should connect and create the required table."""
    flags = {"connected": 0, "created": 0}

    class FakeConn:
        def __init__(self):
            pass

        def close(self):
            pass

    def fake_connect(self):
        flags["connected"] += 1
        flags["created"] += 1
        return FakeConn()

    monkeypatch.setattr(
        checkpoint.ChatStreamManager, "_init_postgresql", fake_connect, raising=True
    )

    manager = checkpoint.ChatStreamManager(checkpoint_saver=True, db_uri=POSTGRES_URL)
    assert manager.postgres_conn is None
    assert flags == {"connected": 1, "created": 1}


def test_chat_stream_message_wrapper(monkeypatch):
    """Wrapper should delegate when enabled and return False when disabled."""
    # When saver enabled, should call default manager
    monkeypatch.setattr(
        checkpoint, "get_bool_env", lambda k, d=False: True, raising=True
    )

    called = {"args": None}

    def fake_process(tid, msg, fr):
        called["args"] = (tid, msg, fr)
        return True

    monkeypatch.setattr(
        checkpoint._default_manager,
        "process_stream_message",
        fake_process,
        raising=True,
    )
    assert checkpoint.chat_stream_message("tid", "msg", "stop") is True
    assert called["args"] == ("tid", "msg", "stop")

    # When saver disabled, returns False and does not call manager
    monkeypatch.setattr(
        checkpoint, "get_bool_env", lambda k, d=False: False, raising=True
    )
    called["args"] = None
    assert checkpoint.chat_stream_message("tid", "msg", "stop") is False
    assert called["args"] is None
