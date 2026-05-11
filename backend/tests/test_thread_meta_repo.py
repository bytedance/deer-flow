"""Tests for ThreadMetaRepository (SQLAlchemy-backed)."""

import logging

import pytest

from deerflow.persistence.thread_meta import ThreadMetaRepository


async def _make_repo(tmp_path):
    from deerflow.persistence.engine import get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return ThreadMetaRepository(get_session_factory())


async def _cleanup():
    from deerflow.persistence.engine import close_engine

    await close_engine()


class TestThreadMetaRepository:
    @pytest.mark.anyio
    async def test_create_and_get(self, tmp_path):
        repo = await _make_repo(tmp_path)
        record = await repo.create("t1")
        assert record["thread_id"] == "t1"
        assert record["status"] == "idle"
        assert "created_at" in record

        fetched = await repo.get("t1")
        assert fetched is not None
        assert fetched["thread_id"] == "t1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_with_assistant_id(self, tmp_path):
        repo = await _make_repo(tmp_path)
        record = await repo.create("t1", assistant_id="agent1")
        assert record["assistant_id"] == "agent1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_with_owner_and_display_name(self, tmp_path):
        repo = await _make_repo(tmp_path)
        record = await repo.create("t1", user_id="user1", display_name="My Thread")
        assert record["user_id"] == "user1"
        assert record["display_name"] == "My Thread"
        await _cleanup()

    @pytest.mark.anyio
    async def test_create_with_metadata(self, tmp_path):
        repo = await _make_repo(tmp_path)
        record = await repo.create("t1", metadata={"key": "value"})
        assert record["metadata"] == {"key": "value"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_get_nonexistent(self, tmp_path):
        repo = await _make_repo(tmp_path)
        assert await repo.get("nonexistent") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_no_record_allows(self, tmp_path):
        repo = await _make_repo(tmp_path)
        assert await repo.check_access("unknown", "user1") is True
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_owner_matches(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user1") is True
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_owner_mismatch(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user2") is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_no_owner_allows_all(self, tmp_path):
        repo = await _make_repo(tmp_path)
        # Explicit user_id=None to bypass the new AUTO default that
        # would otherwise pick up the test user from the autouse fixture.
        await repo.create("t1", user_id=None)
        assert await repo.check_access("t1", "anyone") is True
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_strict_missing_row_denied(self, tmp_path):
        """require_existing=True flips the missing-row case to *denied*.

        Closes the delete-idempotence cross-user gap: after a thread is
        deleted, the row is gone, and the permissive default would let any
        caller "claim" it as untracked. The strict mode demands a row.
        """
        repo = await _make_repo(tmp_path)
        assert await repo.check_access("never-existed", "user1", require_existing=True) is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_strict_owner_match_allowed(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user1", require_existing=True) is True
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_strict_owner_mismatch_denied(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user2", require_existing=True) is False
        await _cleanup()

    @pytest.mark.anyio
    async def test_check_access_strict_null_owner_still_allowed(self, tmp_path):
        """Even in strict mode, a row with NULL user_id stays shared.

        The strict flag tightens the *missing row* case, not the *shared
        row* case — legacy pre-auth rows that survived a clean migration
        without an owner are still everyone's.
        """
        repo = await _make_repo(tmp_path)
        await repo.create("t1", user_id=None)
        assert await repo.check_access("t1", "anyone", require_existing=True) is True
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_status(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1")
        await repo.update_status("t1", "busy")
        record = await repo.get("t1")
        assert record["status"] == "busy"
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1")
        await repo.delete("t1")
        assert await repo.get("t1") is None
        await _cleanup()

    @pytest.mark.anyio
    async def test_delete_nonexistent_is_noop(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.delete("nonexistent")  # should not raise
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_metadata_merges(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"a": 1, "b": 2})
        await repo.update_metadata("t1", {"b": 99, "c": 3})
        record = await repo.get("t1")
        # Existing key preserved, overlapping key overwritten, new key added
        assert record["metadata"] == {"a": 1, "b": 99, "c": 3}
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_metadata_on_empty(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1")
        await repo.update_metadata("t1", {"k": "v"})
        record = await repo.get("t1")
        assert record["metadata"] == {"k": "v"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_update_metadata_nonexistent_is_noop(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.update_metadata("nonexistent", {"k": "v"})  # should not raise
        await _cleanup()

    # --- search with metadata filter (SQL push-down) ---

    @pytest.mark.anyio
    async def test_search_metadata_filter_string(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2", metadata={"env": "staging"})
        await repo.create("t3", metadata={"env": "prod", "region": "us"})

        results = await repo.search(metadata={"env": "prod"})
        ids = {r["thread_id"] for r in results}
        assert ids == {"t1", "t3"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_filter_numeric(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"priority": 1})
        await repo.create("t2", metadata={"priority": 2})
        await repo.create("t3", metadata={"priority": 1, "extra": "x"})

        results = await repo.search(metadata={"priority": 1})
        ids = {r["thread_id"] for r in results}
        assert ids == {"t1", "t3"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_filter_multiple_keys(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"env": "prod", "region": "us"})
        await repo.create("t2", metadata={"env": "prod", "region": "eu"})
        await repo.create("t3", metadata={"env": "staging", "region": "us"})

        results = await repo.search(metadata={"env": "prod", "region": "us"})
        assert len(results) == 1
        assert results[0]["thread_id"] == "t1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_no_match(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"env": "prod"})

        results = await repo.search(metadata={"env": "dev"})
        assert results == []
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_pagination_correct(self, tmp_path):
        """Regression: SQL push-down makes limit/offset exact even when most rows don't match."""
        repo = await _make_repo(tmp_path)
        for i in range(30):
            meta = {"target": "yes"} if i % 3 == 0 else {"target": "no"}
            await repo.create(f"t{i:03d}", metadata=meta)

        # Total matching rows: i in {0,3,6,9,12,15,18,21,24,27} = 10 rows
        all_matches = await repo.search(metadata={"target": "yes"}, limit=100)
        assert len(all_matches) == 10

        # Paginate: first page
        page1 = await repo.search(metadata={"target": "yes"}, limit=3, offset=0)
        assert len(page1) == 3

        # Paginate: second page
        page2 = await repo.search(metadata={"target": "yes"}, limit=3, offset=3)
        assert len(page2) == 3

        # No overlap between pages
        page1_ids = {r["thread_id"] for r in page1}
        page2_ids = {r["thread_id"] for r in page2}
        assert page1_ids.isdisjoint(page2_ids)

        # Last page
        page_last = await repo.search(metadata={"target": "yes"}, limit=3, offset=9)
        assert len(page_last) == 1

        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_with_status_filter(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2", metadata={"env": "prod"})
        await repo.update_status("t1", "busy")

        results = await repo.search(metadata={"env": "prod"}, status="busy")
        assert len(results) == 1
        assert results[0]["thread_id"] == "t1"
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_without_metadata_still_works(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2")

        results = await repo.search(limit=10)
        assert len(results) == 2
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_missing_key_no_match(self, tmp_path):
        """Rows without the requested metadata key should not match."""
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"other": "val"})
        await repo.create("t2", metadata={"env": "prod"})

        results = await repo.search(metadata={"env": "prod"})
        assert len(results) == 1
        assert results[0]["thread_id"] == "t2"
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_unsafe_key_ignored(self, tmp_path, caplog):
        """Unsafe keys are skipped (with warning), so the filter has no effect."""
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2", metadata={"env": "staging"})

        with caplog.at_level(logging.WARNING, logger="deerflow.persistence.thread_meta.sql"):
            results = await repo.search(metadata={"bad;key": "x"})
        assert len(results) == 2
        assert any("bad;key" in r.message for r in caplog.records)
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_filter_boolean(self, tmp_path):
        """True matches only boolean true, not integer 1."""
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"active": True})
        await repo.create("t2", metadata={"active": False})
        await repo.create("t3", metadata={"active": True, "extra": "x"})
        await repo.create("t4", metadata={"active": 1})

        results = await repo.search(metadata={"active": True})
        ids = {r["thread_id"] for r in results}
        assert ids == {"t1", "t3"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_filter_none(self, tmp_path):
        """Only rows with explicit JSON null match; missing key does not."""
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"tag": None})
        await repo.create("t2", metadata={"tag": "present"})
        await repo.create("t3", metadata={"other": "val"})

        results = await repo.search(metadata={"tag": None})
        ids = {r["thread_id"] for r in results}
        assert ids == {"t1"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_safe_json_key_accepts_identifier(self):
        from deerflow.persistence.thread_meta.sql import _is_safe_json_key

        assert _is_safe_json_key("env") is True
        assert _is_safe_json_key("region_us") is True
        assert _is_safe_json_key("_private") is True
        assert _is_safe_json_key("key123") is True
        assert _is_safe_json_key("my-key") is True
        assert _is_safe_json_key("1leading_digit") is True
        assert _is_safe_json_key("a-b-c") is True

    @pytest.mark.anyio
    async def test_safe_json_key_rejects_non_identifier(self):
        from deerflow.persistence.thread_meta.sql import _is_safe_json_key

        assert _is_safe_json_key("a.b") is False
        assert _is_safe_json_key("a.b.c") is False
        assert _is_safe_json_key("a..b") is False
        assert _is_safe_json_key("bad;key") is False
        assert _is_safe_json_key("with space") is False
        assert _is_safe_json_key("") is False

    @pytest.mark.anyio
    async def test_search_metadata_dotted_key_ignored(self, tmp_path, caplog):
        """Dotted keys are rejected and the filter is skipped, not interpreted as nested paths."""
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2", metadata={"env": "staging"})

        with caplog.at_level(logging.WARNING, logger="deerflow.persistence.thread_meta.sql"):
            results = await repo.search(metadata={"a.b": "anything"})
        assert len(results) == 2
        assert any("a.b" in r.message for r in caplog.records)
        await _cleanup()

    # --- dialect-aware type-safe filtering edge cases ---

    @pytest.mark.anyio
    async def test_search_metadata_bool_vs_int_distinction(self, tmp_path):
        """True must not match 1; False must not match 0."""
        repo = await _make_repo(tmp_path)
        await repo.create("bool_true", metadata={"flag": True})
        await repo.create("bool_false", metadata={"flag": False})
        await repo.create("int_one", metadata={"flag": 1})
        await repo.create("int_zero", metadata={"flag": 0})

        true_hits = {r["thread_id"] for r in await repo.search(metadata={"flag": True})}
        assert true_hits == {"bool_true"}

        false_hits = {r["thread_id"] for r in await repo.search(metadata={"flag": False})}
        assert false_hits == {"bool_false"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_int_does_not_match_bool(self, tmp_path):
        """Integer 1 must not match boolean True."""
        repo = await _make_repo(tmp_path)
        await repo.create("bool_true", metadata={"val": True})
        await repo.create("int_one", metadata={"val": 1})

        hits = {r["thread_id"] for r in await repo.search(metadata={"val": 1})}
        assert hits == {"int_one"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_none_excludes_missing_key(self, tmp_path):
        """Filtering by None matches explicit JSON null only, not missing key or empty {}."""
        repo = await _make_repo(tmp_path)
        await repo.create("explicit_null", metadata={"k": None})
        await repo.create("missing_key", metadata={"other": "x"})
        await repo.create("empty_obj", metadata={})

        hits = {r["thread_id"] for r in await repo.search(metadata={"k": None})}
        assert hits == {"explicit_null"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_float_value(self, tmp_path):
        repo = await _make_repo(tmp_path)
        await repo.create("t1", metadata={"score": 3.14})
        await repo.create("t2", metadata={"score": 2.71})
        await repo.create("t3", metadata={"score": 3.14})

        hits = {r["thread_id"] for r in await repo.search(metadata={"score": 3.14})}
        assert hits == {"t1", "t3"}
        await _cleanup()

    @pytest.mark.anyio
    async def test_search_metadata_mixed_types_same_key(self, tmp_path):
        """Each type query only matches its own type, even when the key is shared."""
        repo = await _make_repo(tmp_path)
        await repo.create("str_row", metadata={"x": "hello"})
        await repo.create("int_row", metadata={"x": 42})
        await repo.create("bool_row", metadata={"x": True})
        await repo.create("null_row", metadata={"x": None})

        assert {r["thread_id"] for r in await repo.search(metadata={"x": "hello"})} == {"str_row"}
        assert {r["thread_id"] for r in await repo.search(metadata={"x": 42})} == {"int_row"}
        assert {r["thread_id"] for r in await repo.search(metadata={"x": True})} == {"bool_row"}
        assert {r["thread_id"] for r in await repo.search(metadata={"x": None})} == {"null_row"}
        await _cleanup()


class TestJsonMatchCompilation:
    """Verify compiled SQL for both SQLite and PostgreSQL dialects."""

    def test_json_match_compiles_sqlite(self):
        from sqlalchemy import Column, MetaData, String, Table, create_engine
        from sqlalchemy.types import JSON

        from deerflow.persistence.json_compat import json_match

        metadata = MetaData()
        t = Table("t", metadata, Column("data", JSON), Column("id", String))
        engine = create_engine("sqlite://")

        cases = [
            (None, "json_type(t.data, '$.\"k\"') = 'null'"),
            (True, "json_type(t.data, '$.\"k\"') = 'true'"),
            (False, "json_type(t.data, '$.\"k\"') = 'false'"),
        ]
        for value, expected_fragment in cases:
            expr = json_match(t.c.data, "k", value)
            sql = expr.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True})
            assert str(sql) == expected_fragment, f"value={value!r}: {sql}"

        int_expr = json_match(t.c.data, "k", 42)
        sql = str(int_expr.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True}))
        assert "json_type" in sql
        assert "IN ('integer', 'real')" in sql
        assert "CAST" in sql

        str_expr = json_match(t.c.data, "k", "hello")
        sql = str(str_expr.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True}))
        assert "json_type" in sql
        assert "'text'" in sql

    def test_json_match_compiles_pg(self):
        from sqlalchemy import Column, MetaData, String, Table
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.types import JSON

        from deerflow.persistence.json_compat import json_match

        metadata = MetaData()
        t = Table("t", metadata, Column("data", JSON), Column("id", String))
        dialect = postgresql.dialect()

        cases = [
            (None, "json_typeof(t.data -> 'k') = 'null'"),
            (True, "(json_typeof(t.data -> 'k') = 'boolean' AND (t.data ->> 'k') = 'true')"),
            (False, "(json_typeof(t.data -> 'k') = 'boolean' AND (t.data ->> 'k') = 'false')"),
        ]
        for value, expected_fragment in cases:
            expr = json_match(t.c.data, "k", value)
            sql = expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
            assert str(sql) == expected_fragment, f"value={value!r}: {sql}"

        int_expr = json_match(t.c.data, "k", 42)
        sql = str(int_expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
        assert "json_typeof" in sql
        assert "'number'" in sql
        assert "DOUBLE PRECISION" in sql

        str_expr = json_match(t.c.data, "k", "hello")
        sql = str(str_expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
        assert "json_typeof" in sql
        assert "'string'" in sql

    def test_json_match_rejects_unsafe_key(self):
        from sqlalchemy import Column, MetaData, String, Table
        from sqlalchemy.types import JSON

        from deerflow.persistence.json_compat import json_match

        metadata = MetaData()
        t = Table("t", metadata, Column("data", JSON), Column("id", String))

        for bad_key in ["a.b", "with space", "bad'quote", 'bad"quote', "back\\slash", "semi;colon", ""]:
            with pytest.raises(ValueError, match="JsonMatch key must match"):
                json_match(t.c.data, bad_key, "x")

    def test_json_match_unsupported_dialect_raises(self):
        from sqlalchemy import Column, MetaData, String, Table
        from sqlalchemy.dialects import mysql
        from sqlalchemy.types import JSON

        from deerflow.persistence.json_compat import json_match

        metadata = MetaData()
        t = Table("t", metadata, Column("data", JSON), Column("id", String))
        expr = json_match(t.c.data, "k", "v")

        with pytest.raises(NotImplementedError, match="mysql"):
            str(expr.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
