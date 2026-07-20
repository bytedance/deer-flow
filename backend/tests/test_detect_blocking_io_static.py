from __future__ import annotations

import json
import textwrap
from pathlib import Path

from support.detectors import blocking_io_static as detector


def _write_python(path: Path, source: str) -> Path:
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    return path


def _payload(path: Path, repo_root: Path) -> list[dict[str, object]]:
    return [finding.to_dict() for finding in detector.scan_file(path, repo_root=repo_root)]


def test_scan_file_detects_direct_blocking_calls_in_async_code(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import subprocess
        import time
        import urllib.request
        from pathlib import Path

        async def handler(path: Path):
            time.sleep(1)
            subprocess.run(["echo", "ok"])
            path.read_text(encoding="utf-8")
            with open(path, encoding="utf-8") as handle:
                return urllib.request.urlopen(handle.read())
        """,
    )

    findings = _payload(source_file, tmp_path)
    categories = {finding["blocking_call"]["category"] for finding in findings}
    symbols = {finding["blocking_call"]["symbol"] for finding in findings}

    assert categories == {
        "BLOCKING_FILE_IO",
        "BLOCKING_HTTP_IO",
        "BLOCKING_SLEEP",
        "BLOCKING_SUBPROCESS",
    }
    assert {"time.sleep", "subprocess.run", "path.read_text", "open", "urllib.request.urlopen"}.issubset(symbols)
    assert {finding["event_loop_exposure"] for finding in findings} == {"DIRECT_ASYNC"}


def test_scan_file_detects_blocking_calls_in_sync_helper_reached_from_async_code(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from pathlib import Path

        def load_payload(path: Path) -> bytes:
            return path.read_bytes()

        async def route(path: Path) -> bytes:
            return load_payload(path)
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["blocking_call"]["category"] == "BLOCKING_FILE_IO"
    assert findings[0]["location"]["function"] == "load_payload"
    assert findings[0]["event_loop_exposure"] == "ASYNC_REACHABLE_SAME_FILE"
    assert findings[0]["blocking_call"]["symbol"] == "path.read_bytes"


def test_scan_file_omits_sync_only_blocking_calls_from_default_results(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from pathlib import Path

        def load_payload(path: Path) -> str:
            return path.read_text()
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_detects_self_helper_reached_from_async_method(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class ArtifactRouter:
            def read_payload(self, path):
                return path.read_text(encoding="utf-8")

            async def get(self, path):
                return self.read_payload(path)
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "ArtifactRouter.read_payload"
    assert findings[0]["event_loop_exposure"] == "ASYNC_REACHABLE_SAME_FILE"


def test_scan_file_detects_self_attribute_chain_helper_reached_from_async_method(tmp_path: Path) -> None:
    """self.store.flush() is one hop deeper than the self.flush() case above.

    The receiver (`self.store`) is not the literal Name `self`, so it used to
    fall through every branch in `_record_call_ref` and be silently dropped
    from the call graph -- a false negative for a real blocking call reachable
    from async code.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            def __init__(self, store):
                self.store = store

            async def get(self):
                return self.store.flush()
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "Store.flush"
    assert findings[0]["event_loop_exposure"] == "ASYNC_REACHABLE_SAME_FILE"
    assert findings[0]["blocking_call"]["symbol"] == "open"


def test_scan_file_detects_local_variable_alias_of_self_attribute(tmp_path: Path) -> None:
    """store = self.store; store.flush() must resolve the same as self.store.flush().

    The local variable is traced back, within the same function, to a
    self.-rooted attribute -- the same one-hop-back scope as the constructor
    parameter case below, just through an intermediate local name.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            def __init__(self, store):
                self.store = store

            async def get(self):
                store = self.store
                return store.flush()
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "Store.flush"
    assert findings[0]["event_loop_exposure"] == "ASYNC_REACHABLE_SAME_FILE"
    assert findings[0]["blocking_call"]["symbol"] == "open"


def test_scan_file_detects_constructor_parameter_used_directly_as_receiver(tmp_path: Path) -> None:
    """A function parameter (e.g. a constructor-injected dependency) used
    directly as a call receiver, with no self./cls. attribute in between,
    is the other local-alias origin the fix traces (same function only).
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            def _flush_via(self, store):
                store.flush()

            async def get(self, store):
                return self._flush_via(store)
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "Store.flush"
    assert findings[0]["event_loop_exposure"] == "ASYNC_REACHABLE_SAME_FILE"
    assert findings[0]["blocking_call"]["symbol"] == "open"


def test_scan_file_does_not_trace_unrelated_local_variables_as_receivers(tmp_path: Path) -> None:
    """Scope guardrail: a local variable with no traceable origin (not a
    parameter, not assigned from a self./cls. attribute or another traced
    name) must NOT be resolved through the bare-method-name fallback, or the
    fix would reintroduce broad false positives the tool already avoids.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Unrelated:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        def helper():
            data = compute()
            data.flush()

        async def route():
            return helper()
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_json_output_uses_concise_review_record_schema(tmp_path: Path, capsys) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import subprocess

        async def handler():
            subprocess.run(["echo", "ok"])
        """,
    )

    exit_code = detector.main(["--format", "json", str(source_file)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "priority": "HIGH",
            "location": {
                "path": str(source_file),
                "line": 4,
                "column": 5,
                "function": "handler",
            },
            "blocking_call": {
                "category": "BLOCKING_SUBPROCESS",
                "operation": "SUBPROCESS",
                "symbol": "subprocess.run",
            },
            "event_loop_exposure": "DIRECT_ASYNC",
            "reason": "SUBPROCESS is called directly inside an async function.",
            "code": 'subprocess.run(["echo", "ok"])',
        }
    ]
    assert "confidence" not in payload[0]
    assert "severity" not in payload[0]
    assert "event_loop_risk" not in payload[0]


def test_summary_output_writes_json_report(tmp_path: Path, capsys) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import subprocess

        async def handler():
            subprocess.run(["echo", "ok"])
        """,
    )
    output_path = tmp_path / "reports" / "blocking-io.json"

    exit_code = detector.main(["--output", str(output_path), str(source_file)])

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "Static blocking IO event-loop risk findings: 1" in stdout
    assert "By category:" in stdout
    assert "BLOCKING_SUBPROCESS" in stdout
    assert "Full JSON report:" in stdout
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert [finding["blocking_call"]["category"] for finding in payload] == ["BLOCKING_SUBPROCESS"]


def test_json_output_ranks_operations_without_confidence_noise(tmp_path: Path, capsys) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import shutil

        async def handler(path):
            path.exists()
            path.read_text()
            shutil.rmtree(path)
        """,
    )

    exit_code = detector.main(["--format", "json", str(source_file)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    by_symbol = {finding["blocking_call"]["symbol"]: finding for finding in payload}
    assert by_symbol["path.exists"]["blocking_call"]["operation"] == "FILE_METADATA"
    assert by_symbol["path.exists"]["priority"] == "LOW"
    assert by_symbol["path.read_text"]["blocking_call"]["operation"] == "FILE_READ"
    assert by_symbol["path.read_text"]["priority"] == "MEDIUM"
    assert by_symbol["shutil.rmtree"]["blocking_call"]["operation"] == "FILE_TREE_DELETE"
    assert by_symbol["shutil.rmtree"]["priority"] == "HIGH"
    assert {finding["event_loop_exposure"] for finding in payload} == {"DIRECT_ASYNC"}
    assert all("confidence" not in finding for finding in payload)


def test_path_receiver_detection_uses_path_annotations(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from pathlib import Path

        async def typed(path: Path):
            return path.read_text()

        async def constructed():
            return Path("payload.txt").read_text()
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert {finding["blocking_call"]["symbol"] for finding in findings} == {"path.read_text", "pathlib.Path.read_text"}
    assert {finding["priority"] for finding in findings} == {"MEDIUM"}


def test_summary_groups_findings_by_priority_and_operation(tmp_path: Path, capsys) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os
        from pathlib import Path

        def load_payload(path: Path) -> str:
            return path.read_text()

        async def handler(path: Path) -> str:
            path.exists()
            list(os.walk(path))
            return load_payload(path)
        """,
    )

    exit_code = detector.main([str(source_file)])

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "By priority:" in stdout
    assert "HIGH" in stdout
    assert "MEDIUM" in stdout
    assert "By operation:" in stdout
    assert "FILE_ENUMERATION" in stdout
    assert "FILE_METADATA" in stdout
    assert "FILE_READ" in stdout
    assert "By event-loop exposure:" in stdout
    assert "DIRECT_ASYNC" in stdout
    assert "ASYNC_REACHABLE_SAME_FILE" in stdout


def test_source_code_snippet_is_truncated_for_json_output(tmp_path: Path) -> None:
    long_suffix = " + ".join('"chunk"' for _ in range(80))
    source_file = _write_python(
        tmp_path / "sample.py",
        f"""
        async def handler(path):
            return path.read_text() + {long_suffix}
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert len(findings[0]["code"]) <= 203
    assert findings[0]["code"].endswith("...")


def test_cli_default_filters_sync_only_inventory_items(tmp_path: Path, capsys) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from pathlib import Path

        def load_payload(path: Path) -> str:
            return path.read_text()
        """,
    )

    exit_code = detector.main(["--format", "json", str(source_file)])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_sync_only_agent_middleware_hook_gets_event_loop_exposure(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from langchain.agents.middleware import AgentMiddleware
        from pathlib import Path

        class UploadsMiddleware(AgentMiddleware):
            def before_agent(self, state, runtime):
                return self._load(Path("uploads"))

            def _load(self, path: Path) -> str:
                return path.read_text()
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "UploadsMiddleware._load"
    assert findings[0]["event_loop_exposure"] == "SYNC_AGENT_MIDDLEWARE_HOOK"
    assert "statically reachable from a sync AgentMiddleware hook" in findings[0]["reason"]


def test_sync_agent_middleware_hook_with_async_counterpart_is_not_reported(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from langchain.agents.middleware import AgentMiddleware
        from pathlib import Path

        class UploadsMiddleware(AgentMiddleware):
            def before_agent(self, state, runtime):
                return Path("uploads").read_text()

            async def abefore_agent(self, state, runtime):
                return None
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_detects_sync_httpx_client_methods_in_async_code(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import httpx

        async def search() -> str:
            with httpx.Client(timeout=30) as client:
                return client.post("https://example.invalid").text
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["blocking_call"]["category"] == "BLOCKING_HTTP_IO"
    assert findings[0]["location"]["function"] == "search"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "httpx.Client.post"


def test_scan_file_detects_chained_sync_http_client_methods_in_async_code(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import httpx
        import requests

        async def fetch() -> tuple[object, object]:
            return (
                httpx.Client().get("https://example.invalid"),
                requests.Session().post("https://example.invalid"),
            )
        """,
    )

    findings = _payload(source_file, tmp_path)
    symbols = {finding["blocking_call"]["symbol"] for finding in findings}

    assert symbols == {"httpx.Client.get", "requests.Session.post"}
    assert {finding["blocking_call"]["category"] for finding in findings} == {"BLOCKING_HTTP_IO"}


def test_scan_file_detects_os_walk_and_path_resolve_in_async_code(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os
        from pathlib import Path

        async def inspect_tree(path: Path) -> list[str]:
            root = path.resolve()
            return [name for _, _, names in os.walk(root) for name in names]
        """,
    )

    findings = _payload(source_file, tmp_path)
    symbols = {finding["blocking_call"]["symbol"] for finding in findings}

    assert symbols == {"path.resolve", "os.walk"}
    assert {finding["blocking_call"]["category"] for finding in findings} == {"BLOCKING_FILE_IO"}


def test_scan_file_does_not_treat_string_replace_as_file_io(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        def _path_variants(path: str) -> set[str]:
            return {path, path.replace("\\\\", "/"), path.replace("/", "\\\\")}

        async def normalize(text: str) -> str:
            return text.replace("a", "b")
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_parse_errors_are_reported_as_findings(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "broken.py",
        """
        async def broken(:
            pass
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["blocking_call"]["category"] == "PARSE_ERROR"
    assert findings[0]["priority"] == "MEDIUM"
    assert f"{source_file.name}:1:18" in detector.format_text(detector.scan_file(source_file, repo_root=tmp_path))


def test_scan_file_does_not_treat_call_result_as_receiver_alias(tmp_path: Path) -> None:
    """factory().flush() must not resolve like a traced self./cls./parameter alias.

    `dotted_name()` intentionally unwraps `ast.Call` to build a symbolic name for
    blocking-call pattern matching elsewhere in this module, but reusing that
    unwrap for alias/receiver extraction would treat a call's result as if it
    inherited the callee's own alias-worthiness. `factory` is traceable here (a
    parameter of `get`), so `dotted_name(factory())` unwraps to "factory" and
    used to incorrectly link this call to `Store.flush` below.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            async def get(self, factory):
                return factory().flush()
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_does_not_treat_call_result_assigned_to_local_as_receiver_alias(tmp_path: Path) -> None:
    """client = factory(); client.flush() must not alias client to a traced receiver.

    Same unwrap problem as the direct-call case above, one assignment removed:
    `dotted_name(factory())` returns "factory" (a traced parameter), so `client`
    was incorrectly added to the same-function alias set.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            async def get(self, factory):
                client = factory()
                return client.flush()
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_does_not_treat_subscript_result_as_receiver_alias(tmp_path: Path) -> None:
    """client = clients[0]; client.flush() must not alias client either.

    `dotted_name()` also unwraps `ast.Subscript`, so `dotted_name(clients[0])`
    returned "clients" (a traced parameter), incorrectly aliasing `client`.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            async def get(self, clients):
                client = clients[0]
                return client.flush()
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_kills_alias_after_non_traceable_reassignment(tmp_path: Path) -> None:
    """A non-traceable reassignment must clear a name's existing alias, not just fail to add one.

    `client` starts aliased to `self.store` (traceable), then is reassigned to
    `NonBlockingClient()` (not traceable). The old code only ever added names to
    the alias set and never removed them, so `client` stayed aliased forever and
    `client.flush()` after the reassignment still resolved to `Store.flush`.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class NonBlockingClient:
            def close(self):
                pass

        class Router:
            def __init__(self, store):
                self.store = store

            async def get(self):
                client = self.store
                client = NonBlockingClient()
                return client.flush()
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_if_else_alias_tracking_is_order_independent_across_branches(tmp_path: Path) -> None:
    """Reversing which branch aliases client vs. uses it must not change the result.

    Without a `visit_If` override, `body` and `orelse` shared one mutable alias
    set with no isolation or restore between them, so an alias assigned in
    whichever branch is visited first (always `body`, then `orelse`) leaked into
    the other -- making the finding depend on branch position instead of
    program semantics. Both variants below (same statements, swapped between
    the `if` and `else`) must produce identical output; in this pair neither
    reference is preceded by its assignment on the same execution path, so the
    correct output for both is empty.
    """
    body_first_root = tmp_path / "body_first"
    orelse_first_root = tmp_path / "orelse_first"
    body_first_root.mkdir()
    orelse_first_root.mkdir()

    variant_assign_in_body = _write_python(
        body_first_root / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            def __init__(self, store):
                self.store = store

            async def get(self, flag):
                if flag:
                    client = self.store
                else:
                    client.flush()
                return None
        """,
    )
    variant_assign_in_orelse = _write_python(
        orelse_first_root / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            def __init__(self, store):
                self.store = store

            async def get(self, flag):
                if flag:
                    client.flush()
                else:
                    client = self.store
                return None
        """,
    )

    findings_body_first = _payload(variant_assign_in_body, body_first_root)
    findings_orelse_first = _payload(variant_assign_in_orelse, orelse_first_root)

    assert findings_body_first == findings_orelse_first == []


def test_if_else_alias_union_carries_forward_after_the_if_statement(tmp_path: Path) -> None:
    """A name aliased in only one branch is still (conservatively) aliased after the if.

    This is the other half of the may-alias join: `client` is only assigned
    inside the `if` body, but since either branch might have run, code after
    the whole `if` statement must still treat `client` as possibly aliased.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            def __init__(self, store):
                self.store = store

            async def get(self, flag):
                if flag:
                    client = self.store
                else:
                    pass
                return client.flush()
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "Store.flush"
    assert findings[0]["event_loop_exposure"] == "ASYNC_REACHABLE_SAME_FILE"


def test_scan_file_does_not_treat_default_value_expression_as_inside_new_function(tmp_path: Path) -> None:
    """A default value referencing an outer variable must not be misattributed to the function being defined.

    `receiver` here is a module-level object, unrelated to `route`'s own
    parameter that happens to share its name. `_visit_function` used to push
    the new function's context -- and its parameter-seeded alias set, which
    includes the literal name "receiver" -- before visiting defaults, so
    `receiver.flush()` incorrectly looked like route's own traced parameter
    calling its own method.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        receiver = Store()

        async def route(receiver=receiver.flush()):
            return None
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_definition_time_expressions_are_still_attributed_to_the_enclosing_function(tmp_path: Path) -> None:
    """Decorators/defaults/annotations must move to the enclosing scope, not disappear.

    `helper` is a nested, never-called, sync function -- if its default value's
    blocking call were (incorrectly) attributed to `helper` itself, the finding
    would be silently dropped (helper is neither async nor reachable from
    anything async). Fixing the scope must move the finding to the actual
    enclosing scope that runs it (`outer_async`, which is async), not just make
    it disappear.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import time

        async def outer_async():
            def helper(x=time.sleep(1)):
                return x
            return None
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "outer_async"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "time.sleep"


def test_decorator_default_annotation_and_return_annotation_all_use_enclosing_scope(tmp_path: Path) -> None:
    """All four definition-time expression positions must resolve in the enclosing scope.

    Covers the decorator list, a parameter default, a parameter annotation, and
    the return annotation in one signature -- each pinned to a distinct,
    unconditionally-recognized blocking symbol so a regression in any one
    position produces a non-empty result.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os
        import shutil
        import time

        def _mark(value):
            def _wrap(fn):
                return fn
            return _wrap

        @_mark(time.sleep(1))
        async def route(x=os.listdir("."), y: shutil.rmtree("z") = None) -> time.sleep(2):
            return x
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_pep695_type_parameter_bound_is_never_treated_as_definition_time_eager(tmp_path: Path) -> None:
    """PEP 695 type-parameter bounds are lazily evaluated, not definition-time code.

    CPython compiles a `type_params` bound (`T` in `def helper[T: <bound>](...)`)
    into its own hidden, lazily-invoked function: it only runs if and when
    something accesses `T.__bound__` (e.g. a type checker or `typing` runtime
    introspection), never as part of executing the `def` statement itself --
    not in the function's own scope, and not in the enclosing one either. An
    earlier version of this fix moved the previous `generic_visit` walk of
    `type_params` into the enclosing scope alongside decorators/defaults/
    annotations, on the assumption it was equally eager; that assumption was
    wrong, so bounds are not visited in either scope now.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import time

        async def outer_async():
            def helper[T: time.sleep(1)](x: T) -> T:
                return x
            return None
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_traces_call_result_reassignment_using_pre_assignment_alias_state(tmp_path: Path) -> None:
    """client = client.flush() must resolve the RHS against the PRE-assignment alias state.

    Python evaluates an assignment's RHS before binding its target. `client`
    starts aliased to `self.store` (traceable); reassigning it to
    `client.flush()`'s result correctly kills the alias for code AFTER this
    statement, but the call `client.flush()` itself happens first, while
    `client` was still aliased, and must still be recorded -- updating/killing
    the target's alias before visiting the RHS made this call invisible.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            def __init__(self, store):
                self.store = store

            async def get(self):
                client = self.store
                client = client.flush()
                return client
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "Store.flush"
    assert findings[0]["event_loop_exposure"] == "ASYNC_REACHABLE_SAME_FILE"
    assert findings[0]["blocking_call"]["symbol"] == "open"


def test_scan_file_traces_annassign_call_result_reassignment_using_pre_assignment_alias_state(tmp_path: Path) -> None:
    """Same pre-assignment-alias-state requirement, through an annotated assignment.

    `visit_AnnAssign` shares `visit_Assign`'s RHS-then-target-update ordering
    requirement; this pins it separately so a fix to one path cannot silently
    leave the other regressed.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            def __init__(self, store):
                self.store = store

            async def get(self):
                client: object = self.store
                client: object = client.flush()
                return client
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "Store.flush"
    assert findings[0]["event_loop_exposure"] == "ASYNC_REACHABLE_SAME_FILE"
    assert findings[0]["blocking_call"]["symbol"] == "open"


def test_scan_file_does_not_treat_call_rooted_attribute_chain_as_receiver_alias(tmp_path: Path) -> None:
    """factory().client.flush() must not collapse to the traced name "client".

    `_simple_receiver_name` fell back to returning the trailing attribute name
    whenever the recursive parent lookup came back unsupported (e.g. a Call),
    instead of refusing the whole chain. That let `factory().client` collapse
    to plain "client", which -- because "client" is also a parameter here --
    was then treated exactly like a bare `client.flush()` call on that
    parameter, incorrectly linking this call to `Store.flush` below even
    though `client` is never referenced in this expression at all.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            async def get(self, factory, client):
                return factory().client.flush()
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_does_not_treat_subscript_rooted_attribute_chain_as_receiver_alias(tmp_path: Path) -> None:
    """clients[0].client.flush() must not collapse to the traced name "client" either.

    Same fallback gap as the Call-rooted case above, with `ast.Subscript`
    (rather than `ast.Call`) underneath the final attribute access.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Store:
            def flush(self):
                with open("out.txt", "w") as handle:
                    handle.write("x")

        class Router:
            async def get(self, clients, client):
                return clients[0].client.flush()
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_does_not_treat_postponed_annotation_as_definition_time_eager(tmp_path: Path) -> None:
    """`from __future__ import annotations` defers ALL annotation evaluation.

    With this future import active, CPython never evaluates parameter/return
    annotations at runtime at all (they are kept as unevaluated strings in
    `__annotations__`) -- so a blocking call written in one must not be
    attributed to definition time in any scope, unlike the same shape without
    the future import (see
    `test_decorator_default_annotation_and_return_annotation_all_use_enclosing_scope`).
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from __future__ import annotations

        import os

        async def outer_async():
            def helper(x: os.listdir(".")) -> os.listdir("."):
                return x
            return None
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_does_not_treat_lambda_body_as_definition_time_eager(tmp_path: Path) -> None:
    """A lambda default's BODY must not be treated as running at definition time.

    `helper`'s default value creates a lambda object (eager), but
    `os.listdir(".")` inside its body only runs if and when that lambda is
    later called -- which this snippet never does.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def outer_async():
            def helper(callback=lambda: os.listdir(".")):
                return callback
            return None
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_still_treats_lambda_own_default_as_definition_time_eager(tmp_path: Path) -> None:
    """Contrast case: a lambda's OWN parameter default is genuinely eager.

    Unlike the lambda's body above, its parameter defaults are evaluated
    immediately, when the lambda object itself is created -- so this must
    still be attributed to the enclosing scope like any other default.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def outer_async():
            def helper(callback=lambda flag=os.listdir("."): flag):
                return callback
            return None
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "outer_async"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "os.listdir"


def test_scan_file_does_not_treat_generator_element_as_definition_time_eager(tmp_path: Path) -> None:
    """A bare generator expression's element only runs once iterated, if ever.

    `helper`'s default builds a generator object (eager), but `os.listdir(x)`
    -- the element expression -- is only evaluated lazily as the generator is
    iterated, which this snippet never does.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def outer_async():
            def helper(items=(os.listdir(x) for x in [1])):
                return items
            return None
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_still_treats_generator_outer_iterable_as_definition_time_eager(tmp_path: Path) -> None:
    """Contrast case: a generator's OUTERMOST iterable IS evaluated eagerly.

    Only the first `for`'s iterable runs immediately, to build the generator
    object -- so a blocking call there (unlike the element case above) must
    still be attributed to the enclosing scope.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def outer_async():
            def helper(items=(x for x in os.listdir("."))):
                return items
            return None
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "outer_async"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "os.listdir"


def test_scan_file_treats_immediately_invoked_lambda_as_eager(tmp_path: Path) -> None:
    """An immediately invoked lambda's body is scanned like any other expression.

    `(lambda: ...)()` calls the lambda at the exact expression that defines
    it, in ordinary function-body code -- outside another function's
    definition-time expressions (see `_visit_function`), a lambda's body is
    always scanned regardless of how or whether it is invoked (see also
    `test_scan_file_treats_bare_uninvoked_lambda_as_eager_in_ordinary_code`).
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def route():
            return (lambda: os.listdir("."))()
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "route"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "os.listdir"


def test_scan_file_treats_generator_passed_to_list_as_eager(tmp_path: Path) -> None:
    """A generator passed to `list(...)` is scanned like any other expression.

    In ordinary function-body code -- outside another function's
    definition-time expressions (see `_visit_function`) -- a generator's
    element is always scanned regardless of what, if anything, consumes it
    (see also `test_scan_file_treats_generator_consumed_by_any_builtin_as_eager`
    and `test_scan_file_treats_generator_wrapped_in_map_as_eager`).
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def route():
            return list(os.listdir(path) for path in ["."])
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "route"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "os.listdir"


def test_scan_file_treats_reviewer_repro_both_eager_shapes_together(tmp_path: Path) -> None:
    """Integration check mirroring the exact review repro.

    Both eager shapes -- an immediately invoked lambda and a generator
    consumed by `list(...)` -- appear together in one function, each on its
    own line, and each must produce its own independent finding.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def route():
            first = (lambda: os.listdir("."))()
            second = list(os.listdir(path) for path in ["."])
            return first, second
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 2
    assert {finding["location"]["function"] for finding in findings} == {"route"}
    assert {finding["event_loop_exposure"] for finding in findings} == {"DIRECT_ASYNC"}
    assert {finding["blocking_call"]["symbol"] for finding in findings} == {"os.listdir"}
    assert len({finding["location"]["line"] for finding in findings}) == 2


def test_scan_file_treats_generator_consumed_by_any_builtin_as_eager(tmp_path: Path) -> None:
    """A generator's element is scanned no matter what consumes it.

    In ordinary function-body code, this file does not try to distinguish a
    builtin that eagerly materializes its argument into a container
    (`list`, `set`, `tuple`, `sorted`, `frozenset`, `dict`) from one that
    eagerly reduces it to a scalar (`sum`, `any`, `all`, `min`, `max`) --
    every one of them is scanned the same way, unconditionally, along with a
    builtin that instead wraps the generator in another lazy iterator
    without consuming it at all (see
    `test_scan_file_treats_generator_wrapped_in_map_as_eager`).
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def route():
            a = set(os.listdir(p) for p in ["a"])
            b = tuple(os.listdir(p) for p in ["b"])
            c = sorted(os.listdir(p) for p in ["c"])
            d = frozenset(os.listdir(p) for p in ["d"])
            e = dict((p, os.listdir(p)) for p in ["e"])
            f = sum(len(os.listdir(p)) for p in ["f"])
            g = any(os.listdir(p) for p in ["g"])
            h = all(os.listdir(p) for p in ["h"])
            i = min(len(os.listdir(p)) for p in ["i"])
            j = max(len(os.listdir(p)) for p in ["j"])
            return a, b, c, d, e, f, g, h, i, j
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 10
    assert {finding["location"]["function"] for finding in findings} == {"route"}
    assert {finding["blocking_call"]["symbol"] for finding in findings} == {"os.listdir"}
    assert {finding["event_loop_exposure"] for finding in findings} == {"DIRECT_ASYNC"}


def test_scan_file_treats_generator_reduced_by_sum_as_eager(tmp_path: Path) -> None:
    """`sum(...)` iterates its generator argument immediately, same as `list(...)`.

    A reducer builtin that folds a generator down to a scalar still consumes
    it eagerly to do so, so ordinary code scans it the same as any other
    generator (see also
    `test_scan_file_treats_generator_consumed_by_any_builtin_as_eager`).
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def route():
            return sum(len(os.listdir(path)) for path in ["."])
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "route"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "os.listdir"


def test_scan_file_does_not_treat_immediately_invoked_lambda_in_definition_time_default_as_eager(tmp_path: Path) -> None:
    """Definition-time expressions never scan a nested lambda's body, even an IIFE.

    `helper`'s default value is itself an immediately invoked lambda, so its
    body does run the instant `outer_async` evaluates the default. This file
    does not special-case that: any lambda body or generator element reached
    while walking another function's decorators, parameter defaults/
    annotations, or return annotation is always excluded, full stop (see
    `_visit_function`), the same as an uninvoked one (see
    `test_scan_file_does_not_treat_lambda_body_as_definition_time_eager`
    above). This is a narrow, intentional limitation specific to
    definition-time expressions -- contrast with
    `test_scan_file_treats_immediately_invoked_lambda_as_eager`, where the
    identical shape outside a definition-time context is scanned.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def outer_async():
            def helper(flag=(lambda: os.listdir("."))()):
                return flag
            return None
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_treats_bare_uninvoked_lambda_as_eager_in_ordinary_code(tmp_path: Path) -> None:
    """Ordinary code scans a lambda's body even if it is never called.

    Unlike a lambda used as another function's decorator/default/annotation
    value (see
    `test_scan_file_does_not_treat_lambda_body_as_definition_time_eager`
    above), a lambda created inside a function body is not part of that
    narrow, definition-time-only exclusion. It is scanned unconditionally --
    the same conservative, over-report-rather-than-infer stance this file
    takes for reachability everywhere else: it does not try to prove that a
    lambda (or any other reachable code) is never actually invoked.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def route():
            callback = lambda: os.listdir(".")
            return callback
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "route"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "os.listdir"


def test_scan_file_treats_lambda_invoked_through_stored_variable_as_eager(tmp_path: Path) -> None:
    """A lambda stored in a local and called through that name is still scanned.

    This is the same unconditional lambda-body scan as
    `test_scan_file_treats_bare_uninvoked_lambda_as_eager_in_ordinary_code`
    just above: ordinary code does not track which variable a lambda value
    ends up in or whether/how it is later called, so calling it through the
    stored name makes no difference to the outcome.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def route():
            callback = lambda: os.listdir(".")
            return callback()
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "route"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "os.listdir"


def test_scan_file_treats_bare_unconsumed_generator_as_eager_in_ordinary_code(tmp_path: Path) -> None:
    """Ordinary code scans a generator's element even if it is never iterated.

    Unlike a generator used as another function's decorator/default/
    annotation value (see
    `test_scan_file_does_not_treat_generator_element_as_definition_time_eager`
    above), a generator expression created inside a function body is not
    part of that narrow, definition-time-only exclusion. It is scanned
    unconditionally -- the same stance as
    `test_scan_file_treats_bare_uninvoked_lambda_as_eager_in_ordinary_code`.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def route():
            items = (os.listdir(path) for path in ["."])
            return items
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "route"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "os.listdir"


def test_scan_file_treats_generator_wrapped_in_map_as_eager(tmp_path: Path) -> None:
    """`map(...)` wraps a generator without consuming it, but is still scanned.

    `map(str, gen)` returns another lazy iterator -- it does not iterate
    `gen` at all until the map object itself is consumed, later or never.
    Ordinary code does not try to tell this apart from a builtin that
    consumes the generator eagerly (see
    `test_scan_file_treats_generator_consumed_by_any_builtin_as_eager`) or a
    bare, unconsumed generator (see
    `test_scan_file_treats_bare_unconsumed_generator_as_eager_in_ordinary_code`)
    -- all three are scanned the same way, since telling them apart in
    general means inferring evaluation order across arbitrary code rather
    than reading a fixed, structural fact.
    """
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os

        async def route():
            return map(str, (os.listdir(path) for path in ["."]))
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "route"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "os.listdir"
