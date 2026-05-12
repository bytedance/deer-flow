"""Tests for ThreadMetaRepository (SQLAlchemy-backed)."""

import logging

import pytest

from deerflow.persistence.thread_meta import InvalidMetadataFilterError, ThreadMetaRepository


@pytest.fixture
async def repo(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    yield ThreadMetaRepository(get_session_factory())
    await close_engine()


class TestThreadMetaRepository:
    @pytest.mark.anyio
    async def test_create_and_get(self, repo):
        record = await repo.create("t1")
        assert record["thread_id"] == "t1"
        assert record["status"] == "idle"
        assert "created_at" in record

        fetched = await repo.get("t1")
        assert fetched is not None
        assert fetched["thread_id"] == "t1"

    @pytest.mark.anyio
    async def test_create_with_assistant_id(self, repo):
        record = await repo.create("t1", assistant_id="agent1")
        assert record["assistant_id"] == "agent1"

    @pytest.mark.anyio
    async def test_create_with_owner_and_display_name(self, repo):
        record = await repo.create("t1", user_id="user1", display_name="My Thread")
        assert record["user_id"] == "user1"
        assert record["display_name"] == "My Thread"

    @pytest.mark.anyio
    async def test_create_with_metadata(self, repo):
        record = await repo.create("t1", metadata={"key": "value"})
        assert record["metadata"] == {"key": "value"}

    @pytest.mark.anyio
    async def test_get_nonexistent(self, repo):
        assert await repo.get("nonexistent") is None

    @pytest.mark.anyio
    async def test_check_access_no_record_allows(self, repo):
        assert await repo.check_access("unknown", "user1") is True

    @pytest.mark.anyio
    async def test_check_access_owner_matches(self, repo):
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user1") is True

    @pytest.mark.anyio
    async def test_check_access_owner_mismatch(self, repo):
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user2") is False

    @pytest.mark.anyio
    async def test_check_access_no_owner_allows_all(self, repo):
        # Explicit user_id=None to bypass the new AUTO default that
        # would otherwise pick up the test user from the autouse fixture.
        await repo.create("t1", user_id=None)
        assert await repo.check_access("t1", "anyone") is True

    @pytest.mark.anyio
    async def test_check_access_strict_missing_row_denied(self, repo):
        """require_existing=True flips the missing-row case to *denied*.

        Closes the delete-idempotence cross-user gap: after a thread is
        deleted, the row is gone, and the permissive default would let any
        caller "claim" it as untracked. The strict mode demands a row.
        """
        assert await repo.check_access("never-existed", "user1", require_existing=True) is False

    @pytest.mark.anyio
    async def test_check_access_strict_owner_match_allowed(self, repo):
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user1", require_existing=True) is True

    @pytest.mark.anyio
    async def test_check_access_strict_owner_mismatch_denied(self, repo):
        await repo.create("t1", user_id="user1")
        assert await repo.check_access("t1", "user2", require_existing=True) is False

    @pytest.mark.anyio
    async def test_check_access_strict_null_owner_still_allowed(self, repo):
        """Even in strict mode, a row with NULL user_id stays shared.

        The strict flag tightens the *missing row* case, not the *shared
        row* case — legacy pre-auth rows that survived a clean migration
        without an owner are still everyone's.
        """
        await repo.create("t1", user_id=None)
        assert await repo.check_access("t1", "anyone", require_existing=True) is True

    @pytest.mark.anyio
    async def test_update_status(self, repo):
        await repo.create("t1")
        await repo.update_status("t1", "busy")
        record = await repo.get("t1")
        assert record["status"] == "busy"

    @pytest.mark.anyio
    async def test_delete(self, repo):
        await repo.create("t1")
        await repo.delete("t1")
        assert await repo.get("t1") is None

    @pytest.mark.anyio
    async def test_delete_nonexistent_is_noop(self, repo):
        await repo.delete("nonexistent")  # should not raise

    @pytest.mark.anyio
    async def test_update_metadata_merges(self, repo):
        await repo.create("t1", metadata={"a": 1, "b": 2})
        await repo.update_metadata("t1", {"b": 99, "c": 3})
        record = await repo.get("t1")
        # Existing key preserved, overlapping key overwritten, new key added
        assert record["metadata"] == {"a": 1, "b": 99, "c": 3}

    @pytest.mark.anyio
    async def test_update_metadata_on_empty(self, repo):
        await repo.create("t1")
        await repo.update_metadata("t1", {"k": "v"})
        record = await repo.get("t1")
        assert record["metadata"] == {"k": "v"}

    @pytest.mark.anyio
    async def test_update_metadata_nonexistent_is_noop(self, repo):
        await repo.update_metadata("nonexistent", {"k": "v"})  # should not raise

    # --- search with metadata filter (SQL push-down) ---

    @pytest.mark.anyio
    async def test_search_metadata_filter_string(self, repo):
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2", metadata={"env": "staging"})
        await repo.create("t3", metadata={"env": "prod", "region": "us"})

        results = await repo.search(metadata={"env": "prod"})
        ids = {r["thread_id"] for r in results}
        assert ids == {"t1", "t3"}

    @pytest.mark.anyio
    async def test_search_metadata_filter_numeric(self, repo):
        await repo.create("t1", metadata={"priority": 1})
        await repo.create("t2", metadata={"priority": 2})
        await repo.create("t3", metadata={"priority": 1, "extra": "x"})

        results = await repo.search(metadata={"priority": 1})
        ids = {r["thread_id"] for r in results}
        assert ids == {"t1", "t3"}

    @pytest.mark.anyio
    async def test_search_metadata_filter_multiple_keys(self, repo):
        await repo.create("t1", metadata={"env": "prod", "region": "us"})
        await repo.create("t2", metadata={"env": "prod", "region": "eu"})
        await repo.create("t3", metadata={"env": "staging", "region": "us"})

        results = await repo.search(metadata={"env": "prod", "region": "us"})
        assert len(results) == 1
        assert results[0]["thread_id"] == "t1"

    @pytest.mark.anyio
    async def test_search_metadata_no_match(self, repo):
        await repo.create("t1", metadata={"env": "prod"})

        results = await repo.search(metadata={"env": "dev"})
        assert results == []

    @pytest.mark.anyio
    async def test_search_metadata_pagination_correct(self, repo):
        """Regression: SQL push-down makes limit/offset exact even when most rows don't match."""
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

    @pytest.mark.anyio
    async def test_search_metadata_with_status_filter(self, repo):
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2", metadata={"env": "prod"})
        await repo.update_status("t1", "busy")

        results = await repo.search(metadata={"env": "prod"}, status="busy")
        assert len(results) == 1
        assert results[0]["thread_id"] == "t1"

    @pytest.mark.anyio
    async def test_search_without_metadata_still_works(self, repo):
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2")

        results = await repo.search(limit=10)
        assert len(results) == 2

    @pytest.mark.anyio
    async def test_search_metadata_missing_key_no_match(self, repo):
        """Rows without the requested metadata key should not match."""
        await repo.create("t1", metadata={"other": "val"})
        await repo.create("t2", metadata={"env": "prod"})

        results = await repo.search(metadata={"env": "prod"})
        assert len(results) == 1
        assert results[0]["thread_id"] == "t2"

    @pytest.mark.anyio
    async def test_search_metadata_all_unsafe_keys_raises(self, repo, caplog):
        """When ALL metadata keys are unsafe, raises InvalidMetadataFilterError."""
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2", metadata={"env": "staging"})

        with caplog.at_level(logging.WARNING, logger="deerflow.persistence.thread_meta.sql"):
            with pytest.raises(InvalidMetadataFilterError, match="rejected") as exc_info:
                await repo.search(metadata={"bad;key": "x"})
        assert any("bad;key" in r.message for r in caplog.records)
        # Subclass of ValueError for backward compatibility
        assert isinstance(exc_info.value, ValueError)

    @pytest.mark.anyio
    async def test_search_metadata_partial_unsafe_key_skipped(self, repo, caplog):
        """Valid keys filter rows; only the invalid key is warned and skipped."""
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2", metadata={"env": "staging"})

        with caplog.at_level(logging.WARNING, logger="deerflow.persistence.thread_meta.sql"):
            results = await repo.search(metadata={"env": "prod", "bad;key": "x"})
        ids = {r["thread_id"] for r in results}
        assert ids == {"t1"}
        assert any("bad;key" in r.message for r in caplog.records)

    @pytest.mark.anyio
    async def test_search_metadata_filter_boolean(self, repo):
        """True matches only boolean true, not integer 1."""
        await repo.create("t1", metadata={"active": True})
        await repo.create("t2", metadata={"active": False})
        await repo.create("t3", metadata={"active": True, "extra": "x"})
        await repo.create("t4", metadata={"active": 1})

        results = await repo.search(metadata={"active": True})
        ids = {r["thread_id"] for r in results}
        assert ids == {"t1", "t3"}

    @pytest.mark.anyio
    async def test_search_metadata_filter_none(self, repo):
        """Only rows with explicit JSON null match; missing key does not."""
        await repo.create("t1", metadata={"tag": None})
        await repo.create("t2", metadata={"tag": "present"})
        await repo.create("t3", metadata={"other": "val"})

        results = await repo.search(metadata={"tag": None})
        ids = {r["thread_id"] for r in results}
        assert ids == {"t1"}

    @pytest.mark.anyio
    async def test_search_metadata_non_string_key_skipped(self, repo, caplog):
        """Non-string keys raise ValueError from isinstance check; should be warned and skipped."""
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2", metadata={"env": "staging"})

        with caplog.at_level(logging.WARNING, logger="deerflow.persistence.thread_meta.sql"):
            with pytest.raises(InvalidMetadataFilterError, match="rejected"):
                await repo.search(metadata={1: "x"})
        assert any("1" in r.message for r in caplog.records)

    @pytest.mark.anyio
    async def test_search_metadata_unsupported_value_type_skipped(self, repo, caplog):
        """Unsupported value types (list, dict) raise TypeError; should be warned and skipped."""
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2", metadata={"env": "staging"})

        with caplog.at_level(logging.WARNING, logger="deerflow.persistence.thread_meta.sql"):
            with pytest.raises(InvalidMetadataFilterError, match="rejected"):
                await repo.search(metadata={"env": ["prod", "staging"]})

    @pytest.mark.anyio
    async def test_search_metadata_dotted_key_raises(self, repo, caplog):
        """Dotted keys are rejected; when ALL keys are dotted, raises ValueError."""
        await repo.create("t1", metadata={"env": "prod"})
        await repo.create("t2", metadata={"env": "staging"})

        with caplog.at_level(logging.WARNING, logger="deerflow.persistence.thread_meta.sql"):
            with pytest.raises(InvalidMetadataFilterError, match="rejected"):
                await repo.search(metadata={"a.b": "anything"})
        assert any("a.b" in r.message for r in caplog.records)

    # --- dialect-aware type-safe filtering edge cases ---

    @pytest.mark.anyio
    async def test_search_metadata_bool_vs_int_distinction(self, repo):
        """True must not match 1; False must not match 0."""
        await repo.create("bool_true", metadata={"flag": True})
        await repo.create("bool_false", metadata={"flag": False})
        await repo.create("int_one", metadata={"flag": 1})
        await repo.create("int_zero", metadata={"flag": 0})

        true_hits = {r["thread_id"] for r in await repo.search(metadata={"flag": True})}
        assert true_hits == {"bool_true"}

        false_hits = {r["thread_id"] for r in await repo.search(metadata={"flag": False})}
        assert false_hits == {"bool_false"}

    @pytest.mark.anyio
    async def test_search_metadata_int_does_not_match_bool(self, repo):
        """Integer 1 must not match boolean True."""
        await repo.create("bool_true", metadata={"val": True})
        await repo.create("int_one", metadata={"val": 1})

        hits = {r["thread_id"] for r in await repo.search(metadata={"val": 1})}
        assert hits == {"int_one"}

    @pytest.mark.anyio
    async def test_search_metadata_none_excludes_missing_key(self, repo):
        """Filtering by None matches explicit JSON null only, not missing key or empty {}."""
        await repo.create("explicit_null", metadata={"k": None})
        await repo.create("missing_key", metadata={"other": "x"})
        await repo.create("empty_obj", metadata={})

        hits = {r["thread_id"] for r in await repo.search(metadata={"k": None})}
        assert hits == {"explicit_null"}

    @pytest.mark.anyio
    async def test_search_metadata_float_value(self, repo):
        await repo.create("t1", metadata={"score": 3.14})
        await repo.create("t2", metadata={"score": 2.71})
        await repo.create("t3", metadata={"score": 3.14})

        hits = {r["thread_id"] for r in await repo.search(metadata={"score": 3.14})}
        assert hits == {"t1", "t3"}

    @pytest.mark.anyio
    async def test_search_metadata_mixed_types_same_key(self, repo):
        """Each type query only matches its own type, even when the key is shared."""
        await repo.create("str_row", metadata={"x": "hello"})
        await repo.create("int_row", metadata={"x": 42})
        await repo.create("bool_row", metadata={"x": True})
        await repo.create("null_row", metadata={"x": None})

        assert {r["thread_id"] for r in await repo.search(metadata={"x": "hello"})} == {"str_row"}
        assert {r["thread_id"] for r in await repo.search(metadata={"x": 42})} == {"int_row"}
        assert {r["thread_id"] for r in await repo.search(metadata={"x": True})} == {"bool_row"}
        assert {r["thread_id"] for r in await repo.search(metadata={"x": None})} == {"null_row"}

    @pytest.mark.anyio
    async def test_search_metadata_large_int_precision(self, repo):
        """Integers beyond float precision (> 2**53) must match exactly."""
        large = 2**53 + 1
        await repo.create("t1", metadata={"id": large})
        await repo.create("t2", metadata={"id": large - 1})

        hits = {r["thread_id"] for r in await repo.search(metadata={"id": large})}
        assert hits == {"t1"}


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

        # int: uses INTEGER cast for precision, type-check narrows to 'integer' only
        int_expr = json_match(t.c.data, "k", 42)
        sql = str(int_expr.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True}))
        assert "json_type" in sql
        assert "= 'integer'" in sql
        assert "INTEGER" in sql
        assert "CAST" in sql

        # float: uses REAL cast, type-check spans 'integer' and 'real'
        float_expr = json_match(t.c.data, "k", 3.14)
        sql = str(float_expr.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True}))
        assert "json_type" in sql
        assert "IN ('integer', 'real')" in sql
        assert "REAL" in sql

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

        # int: CASE guard prevents CAST error when 'number' also matches floats
        int_expr = json_match(t.c.data, "k", 42)
        sql = str(int_expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
        assert "json_typeof" in sql
        assert "'number'" in sql
        assert "BIGINT" in sql
        assert "CASE WHEN" in sql
        assert "'^-?[0-9]+$'" in sql

        # float: uses DOUBLE PRECISION cast
        float_expr = json_match(t.c.data, "k", 3.14)
        sql = str(float_expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
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

        # Non-string keys must also raise ValueError (not TypeError from re.match)
        for non_str_key in [42, None, ("k",)]:
            with pytest.raises(ValueError, match="JsonMatch key must match"):
                json_match(t.c.data, non_str_key, "x")

    def test_json_match_rejects_unsupported_value_type(self):
        from sqlalchemy import Column, MetaData, String, Table
        from sqlalchemy.types import JSON

        from deerflow.persistence.json_compat import json_match

        metadata = MetaData()
        t = Table("t", metadata, Column("data", JSON), Column("id", String))

        for bad_value in [[], {}, object()]:
            with pytest.raises(TypeError, match="JsonMatch value must be"):
                json_match(t.c.data, "k", bad_value)

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

    def test_json_match_rejects_out_of_range_int(self):
        from sqlalchemy import Column, MetaData, String, Table
        from sqlalchemy.types import JSON

        from deerflow.persistence.json_compat import json_match

        metadata = MetaData()
        t = Table("t", metadata, Column("data", JSON), Column("id", String))

        # boundary values must be accepted
        json_match(t.c.data, "k", 2**63 - 1)
        json_match(t.c.data, "k", -(2**63))

        # one beyond each boundary must be rejected
        for out_of_range in [2**63, -(2**63) - 1, 10**30]:
            with pytest.raises(TypeError, match="out of signed 64-bit range"):
                json_match(t.c.data, "k", out_of_range)

    def test_compiler_raises_on_escaped_key(self):
        """Compiler raises ValueError even when __init__ validation is bypassed."""
        from sqlalchemy import Column, MetaData, String, Table, create_engine
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.types import JSON

        from deerflow.persistence.json_compat import json_match

        metadata = MetaData()
        t = Table("t", metadata, Column("data", JSON), Column("id", String))
        engine = create_engine("sqlite://")

        elem = json_match(t.c.data, "k", "v")
        elem.key = "bad.key"  # bypass __init__ to simulate -O stripping assert

        with pytest.raises(ValueError, match="Key escaped validation"):
            str(elem.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True}))

        with pytest.raises(ValueError, match="Key escaped validation"):
            str(elem.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
