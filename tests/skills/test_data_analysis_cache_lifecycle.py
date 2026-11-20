"""Real DuckDB cache lifetimes, using the production CSV loader without spatial."""

import errno
import json
import multiprocessing
import runpy
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("openpyxl")
SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/data-analysis/scripts/analyze.py"
)


def configure(cache, source):
    module = runpy.run_path(str(SCRIPT))
    scope = module["main"].__globals__
    scope["CACHE_DIR"] = str(cache)

    def load_csv(con, files):
        # Replace load_files dispatch with production CSV loading, avoiding the
        # optional INSTALL spatial setup. Cache, SQL and filesystem stay real.
        tables = {}
        for path in files:
            scope["_load_csv"](con, path, tables)
        return tables

    scope["load_files"] = load_csv
    sys.argv = [str(SCRIPT), "--files", str(source), "--action", "inspect"]
    return scope


def worker(
    cache,
    source,
    started,
    finish,
    results,
    hold,
    load_barrier=None,
    *,
    require_cache_hit=False,
):
    try:
        scope = configure(cache, source)
        if require_cache_hit:
            scope["load_files"] = lambda *_: pytest.fail(
                "reader must reuse the published cache"
            )
        if load_barrier is not None:
            loader = scope["load_files"]

            def gated_load(con, files):
                load_barrier.wait(10)
                return loader(con, files)

            scope["load_files"] = gated_load

        def inspect(con, tables):
            if hold:
                started.set()
                if not finish.wait(10):
                    raise TimeoutError("parent did not release analysis")
            value = con.execute('SELECT value FROM "report"').fetchall()
            results.put(("ok", value))

        scope["action_inspect"] = inspect
        scope["main"]()
    except BaseException as error:
        results.put(("error", type(error).__name__, str(error)))


@pytest.fixture
def input_file(tmp_path):
    source = tmp_path / "report.csv"
    source.write_text("value\n7\n", encoding="utf-8")
    return source


def test_second_process_reads_while_first_action_is_running(tmp_path, input_file):
    ctx = multiprocessing.get_context("spawn")
    started, finish, results = ctx.Event(), ctx.Event(), ctx.Queue()
    cache = tmp_path / "cache"
    first = ctx.Process(
        target=worker, args=(cache, input_file, started, finish, results, True)
    )
    second = ctx.Process(
        target=worker, args=(cache, input_file, started, finish, results, False)
    )
    first.start()
    try:
        assert started.wait(10), "first analysis must reach the action boundary"
        second.start()
        result = results.get(timeout=10)
        assert result == ("ok", [(7,)]), "cache reader overlapped a live writer"
        finish.set()
        assert results.get(timeout=10) == ("ok", [(7,)])
    finally:
        finish.set()
        for process in (first, second):
            if process.pid is not None:
                process.join(10)
                if process.is_alive():
                    process.terminate()
                    process.join(5)
        results.close()


def test_failed_loader_leaves_no_database_for_retry(tmp_path, input_file):
    cache = tmp_path / "cache"
    scope = configure(cache, input_file)
    loader = scope["load_files"]

    def fail(con, files):
        loader(con, files)
        raise RuntimeError("loader interrupted after writing tables")

    scope["load_files"] = fail
    with pytest.raises(RuntimeError, match="loader interrupted"):
        scope["main"]()
    assert list(cache.rglob("*.duckdb")) == []


def publication_worker(cache, source, published, release, results):
    """Pause after real manifest publication, before its caller continues."""
    try:
        scope = configure(cache, source)

        # The regression also runs against the flat-cache implementation. Its
        # publication point exposes the map before closing the DuckDB writer.
        def pause():
            published.set()
            if not release.wait(10):
                raise TimeoutError("parent did not release publication")

        if "save_table_map" in scope:
            save = scope["save_table_map"]

            def pause_after_map(*args):
                save(*args)
                pause()

            scope["save_table_map"] = pause_after_map
        else:
            replace = scope["os"].replace

            def pause_after_replace(source_path, destination):
                replace(source_path, destination)
                if Path(destination).parent == cache / "generations-v1":
                    pause()

            scope["os"].replace = pause_after_replace
        scope["action_inspect"] = lambda con, _: con.execute(
            "SELECT value FROM report"
        ).fetchall()
        scope["main"]()
        results.put(("publisher-ok",))
    except BaseException as error:
        results.put(("error", type(error).__name__, str(error)))


def test_reader_can_open_cache_at_publication_barrier(tmp_path, input_file):
    """Publishing metadata must imply an independently readable database."""
    ctx = multiprocessing.get_context("spawn")
    published, release, results = ctx.Event(), ctx.Event(), ctx.Queue()
    cache = tmp_path / "cache"
    publisher = ctx.Process(
        target=publication_worker, args=(cache, input_file, published, release, results)
    )
    reader = ctx.Process(
        target=worker,
        args=(cache, input_file, published, release, results, False),
        kwargs={"require_cache_hit": True},
    )
    publisher.start()
    try:
        assert published.wait(10), "publisher must reach its real metadata publication"
        reader.start()
        assert results.get(timeout=10) == ("ok", [(7,)]), (
            "published cache is still owned by an import writer"
        )
        release.set()
        assert results.get(timeout=10) == ("publisher-ok",)
    finally:
        release.set()
        for process in (publisher, reader):
            if process.pid is not None:
                process.join(10)
                if process.is_alive():
                    process.terminate()
                    process.join(5)
        results.close()


def test_action_failure_closes_connection(tmp_path, input_file, monkeypatch):
    scope = configure(tmp_path / "cache", input_file)
    connect = duckdb.connect
    opened = []

    def recording_connect(*args, **kwargs):
        con = connect(*args, **kwargs)
        opened.append(con)
        return con

    def fail(*args):
        raise RuntimeError("action failed")

    monkeypatch.setattr(duckdb, "connect", recording_connect)
    scope["action_inspect"] = fail
    with pytest.raises(RuntimeError, match="action failed"):
        scope["main"]()
    assert opened
    for con in opened:
        with pytest.raises(duckdb.ConnectionException):
            con.execute("SELECT 1")


def test_corrupt_table_map_rebuilds_before_action(tmp_path, input_file):
    cache = tmp_path / "cache"
    scope = configure(cache, input_file)
    seen = []
    loader = scope["load_files"]

    def record_load(con, files):
        seen.append("load")
        return loader(con, files)

    scope["load_files"] = record_load
    scope["action_inspect"] = lambda con, tables: con.execute(
        'SELECT value FROM "' + tables["report"] + '"'
    ).fetchall()
    scope["main"]()
    manifests = list(cache.rglob("*.json"))
    assert len(manifests) == 1
    data = json.loads(manifests[0].read_text(encoding="utf-8"))
    if "table_map" in data:
        data["table_map"] = {"report": "missing"}
    else:
        data = {"report": "missing"}
    manifests[0].write_text(json.dumps(data), encoding="utf-8")
    scope["main"]()
    assert seen == ["load", "load"]


def test_simultaneous_cold_processes_publish_complete_generations(tmp_path, input_file):
    ctx = multiprocessing.get_context("spawn")
    started, finish, results, barrier = (
        ctx.Event(),
        ctx.Event(),
        ctx.Queue(),
        ctx.Barrier(2),
    )
    cache = tmp_path / "cache"
    processes = [
        ctx.Process(
            target=worker,
            args=(cache, input_file, started, finish, results, False, barrier),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    try:
        assert [results.get(timeout=15) for _ in processes] == [
            ("ok", [(7,)]),
            ("ok", [(7,)]),
        ]
        scope = configure(cache, input_file)
        scope["load_files"] = lambda *_: pytest.fail("published cache must be reusable")
        with scope["open_analysis_cache"]([str(input_file)]) as (con, tables):
            assert con.execute('SELECT value FROM "report"').fetchall() == [(7,)]
            assert tables == {"report": "report"}
    finally:
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
        results.close()


def manifest(cache):
    paths = list(cache.rglob("*.json"))
    assert len(paths) == 1
    return paths[0], json.loads(paths[0].read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "damaged_map",
    [
        {"report": "report", "report_1": "report"},
        {"report": "report_1", "other": "report"},
        {"report": "report"},
        {"Report": "report", "report": "report_1"},
    ],
)
def test_inconsistent_manifest_rebuilds_without_redirecting_sources(
    tmp_path, input_file, damaged_map
):
    second = tmp_path / "other" / "report.csv"
    second.parent.mkdir()
    second.write_text("value\n99\n", encoding="utf-8")
    files = [str(input_file), str(second)]
    cache = tmp_path / "cache"
    scope = configure(cache, input_file)
    with scope["open_analysis_cache"](files):
        pass
    path, data = manifest(cache)
    data["table_map"] = damaged_map
    path.write_text(json.dumps(data), encoding="utf-8")
    loads = []
    loader = scope["load_files"]

    def record_load(con, paths):
        loads.append(True)
        return loader(con, paths)

    scope["load_files"] = record_load
    with scope["open_analysis_cache"](files) as (con, tables):
        assert tables == {"report": "report", "report_1": "report_1"}
        assert con.execute("SELECT value FROM report").fetchall() == [(7,)]
        assert con.execute("SELECT value FROM report_1").fetchall() == [(99,)]
    assert loads == [True]


def test_reader_keeps_old_generation_during_repair(tmp_path, input_file):
    cache = tmp_path / "cache"
    scope = configure(cache, input_file)
    with scope["open_analysis_cache"]([str(input_file)]) as (old, _):
        path, data = manifest(cache)
        data["format"] = 0
        path.write_text(json.dumps(data), encoding="utf-8")
        with scope["open_analysis_cache"]([str(input_file)]) as (new, tables):
            assert new.execute('SELECT value FROM "report"').fetchall() == [(7,)]
            assert tables == {"report": "report"}
            assert old.execute('SELECT value FROM "report"').fetchall() == [(7,)]
        assert old.execute('SELECT value FROM "report"').fetchall() == [(7,)]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {},
        {"format": True},
        {"format": 2},
        {"format": 1, "generation": "../../outside", "table_map": {"report": "report"}},
    ],
)
def test_invalid_manifest_is_rebuilt(tmp_path, input_file, bad):
    cache = tmp_path / "cache"
    scope = configure(cache, input_file)
    scope["main"]()
    path, _ = manifest(cache)
    path.write_text(json.dumps(bad), encoding="utf-8")
    rebuilt = []
    loader = scope["load_files"]
    scope["load_files"] = lambda con, files: (rebuilt.append(True), loader(con, files))[
        1
    ]
    scope["main"]()
    assert rebuilt == [True]


@pytest.mark.parametrize("damage", ["missing", "truncated"])
def test_missing_or_corrupt_database_is_rebuilt(tmp_path, input_file, damage):
    cache = tmp_path / "cache"
    scope = configure(cache, input_file)
    scope["main"]()
    _, data = manifest(cache)
    path = cache / "generations-v1" / data["generation"] / "data.duckdb"
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"not a database")
    scope["main"]()
    with scope["open_analysis_cache"]([str(input_file)]) as (con, _):
        assert con.execute('SELECT value FROM "report"').fetchall() == [(7,)]


@pytest.mark.parametrize(
    "failure", [RuntimeError("failed"), KeyboardInterrupt(), SystemExit(2)]
)
def test_load_interruption_cleans_private_build(tmp_path, input_file, failure):
    cache = tmp_path / "cache"
    scope = configure(cache, input_file)
    loader = scope["load_files"]

    def fail(con, files):
        loader(con, files)
        raise failure

    scope["load_files"] = fail
    with pytest.raises(type(failure)):
        scope["main"]()
    assert list(cache.rglob("*.duckdb")) == []
    assert list(cache.rglob("*.json")) == []
    scope["load_files"] = loader
    scope["main"]()


@pytest.mark.parametrize(
    ("module", "operation"),
    [("tempfile", "mkstemp"), ("json", "dump"), ("os", "fsync")],
)
def test_manifest_preparation_failure_cleans_private_generation(
    tmp_path, input_file, monkeypatch, module, operation
):
    cache = tmp_path / "cache"
    scope = configure(cache, input_file)

    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "manifest preparation ran out of space")

    with monkeypatch.context() as patch:
        patch.setattr(scope[module], operation, fail)
        with pytest.raises(OSError) as error:
            scope["main"]()
    assert error.value.errno == errno.ENOSPC
    assert list((cache / "generations-v1").iterdir()) == []

    with scope["open_analysis_cache"]([str(input_file)]) as (con, _):
        assert con.execute("SELECT value FROM report").fetchall() == [(7,)]


def test_publication_failure_preserves_prior_manifest(
    tmp_path, input_file, monkeypatch
):
    cache = tmp_path / "cache"
    scope = configure(cache, input_file)
    scope["main"]()
    path, data = manifest(cache)
    data["format"] = 0  # Force repair, retaining the original publication.
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    original_generations = set(cache.rglob("*.duckdb"))

    def fail(*args):
        raise OSError("publication failed")

    with monkeypatch.context() as patch:
        patch.setattr(scope["os"], "replace", fail)
        with pytest.raises(OSError, match="publication failed"):
            scope["main"]()
    assert path.read_bytes() == before
    assert set(cache.rglob("*.duckdb")) == original_generations
    assert list(cache.rglob("*.tmp")) == []
    scope["main"]()


def test_failed_replacement_retries_remove_private_generations(tmp_path, input_file):
    cache = tmp_path / "cache"
    scope = configure(cache, input_file)
    root = cache / "generations-v1"
    manifest_path = root / f"{scope['compute_files_hash']([str(input_file)])}.json"
    manifest_path.mkdir(parents=True)

    # A directory at the destination makes the real atomic replacement fail.
    for _ in range(3):
        with pytest.raises(OSError) as error:
            scope["main"]()
        assert Path(error.value.filename2) == manifest_path
        assert list(root.iterdir()) == [manifest_path]

    manifest_path.rmdir()
    with scope["open_analysis_cache"]([str(input_file)]) as (con, _):
        assert con.execute("SELECT value FROM report").fetchall() == [(7,)]


def test_interrupted_cache_validation_closes_reader(tmp_path, input_file, monkeypatch):
    scope = configure(tmp_path / "cache", input_file)
    scope["main"]()
    connect = duckdb.connect
    opened = []

    class InterruptedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, *_):
            raise KeyboardInterrupt()

        def close(self):
            self.connection.close()

    def wrapped_connect(*args, **kwargs):
        con = connect(*args, **kwargs)
        opened.append(con)
        return InterruptedConnection(con)

    monkeypatch.setattr(duckdb, "connect", wrapped_connect)
    with pytest.raises(KeyboardInterrupt):
        scope["main"]()
    assert opened
    with pytest.raises(duckdb.ConnectionException):
        opened[0].execute("SELECT 1")


def test_interruption_after_replace_keeps_published_generation(
    tmp_path, input_file, monkeypatch
):
    scope = configure(tmp_path / "cache", input_file)
    replace = scope["os"].replace

    def publish_then_interrupt(*args):
        replace(*args)
        raise KeyboardInterrupt()

    with monkeypatch.context() as patch:
        patch.setattr(scope["os"], "replace", publish_then_interrupt)
        with pytest.raises(KeyboardInterrupt):
            scope["main"]()
    scope["load_files"] = lambda *_: pytest.fail(
        "a published generation must remain readable"
    )
    with scope["open_analysis_cache"]([str(input_file)]) as (con, _):
        assert con.execute("SELECT value FROM report").fetchall() == [(7,)]
