"""Lark CLI sandbox credential broker (Pattern B, issue #4338).

Pattern A (PR #3971) provisions the ``lark-cli`` *binary* into the sandbox but
still mounts the per-user credential directories (``config`` with the long-lived
``appSecret`` and ``data`` with OAuth tokens) into the sandbox container, where
the agent's ``bash`` tool can read them.

This module implements the broker half of Pattern B: a long-lived process that
owns ``lark-cli`` + the credentials and exposes only the *command surface* over
loopback. The sandbox gets a tiny ``lark-cli`` shim on ``PATH`` that forwards
argv/stdin to the broker, so the raw credential files never exist in the sandbox
filesystem.

Everything here is Python-3-stdlib only so the same module can run inside the
minimal broker sidecar image without extra dependencies.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger(__name__)

# ── Loopback wire contract ────────────────────────────────────────────────

# The sandbox and the broker sidecar share the Pod network namespace, so the
# shim reaches the broker on loopback. The port is fixed and injected into the
# sandbox as DEERFLOW_LARK_BROKER_URL.
LARK_BROKER_DEFAULT_HOST = "127.0.0.1"
LARK_BROKER_DEFAULT_PORT = 8788
LARK_BROKER_URL_ENV = "DEERFLOW_LARK_BROKER_URL"
LARK_BROKER_EXEC_PATH = "/v1/exec"
LARK_BROKER_HEALTH_PATH = "/v1/health"

# Guards. Bounded so a compromised sandbox cannot exhaust the broker.
LARK_BROKER_MAX_REQUEST_BYTES = 1 * 1024 * 1024
LARK_BROKER_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
LARK_BROKER_DEFAULT_TIMEOUT_SECONDS = 120
LARK_BROKER_MAX_CONCURRENCY = 8
# Per-connection socket timeout. ThreadingHTTPServer spawns a thread per
# connection, so without this a sandbox could declare a large Content-Length and
# never send the body, parking a thread forever. Bounds the read so a slow/stuck
# client releases its thread. (Loopback-only, so this only guards the sandbox
# against tying up its own broker.)
LARK_BROKER_SOCKET_TIMEOUT_SECONDS = 30

# Optional env knob (comma-separated) for the subcommand denylist below.
LARK_BROKER_DENY_SUBCOMMANDS_ENV = "DEERFLOW_LARK_BROKER_DENY_SUBCOMMANDS"

# The runtime layout the sandbox sees is two files in ``bin/``:
#
#   bin/lark-cli          the POSIX-sh *launcher* (below) — the executable on PATH
#   bin/lark-cli-shim.py  the Python *shim* body (below) it execs
#
# Pattern A's launcher is pure ``#!/bin/sh`` (it just execs the arch-dispatched
# binary) and therefore has no runtime deps. The broker shim has to speak HTTP,
# so it is Python — but shipping it as a bare ``#!/usr/bin/env python3`` script
# would make every ``lark-cli`` call ENOEXEC/exit-127 on a sandbox image without
# ``python3`` on PATH, and because broker mode is opt-in that could slip past CI
# and only surface for an operator. The ``/bin/sh`` launcher resolves a Python 3
# interpreter itself (using only shell built-ins, so it still works when PATH is
# empty and the interpreter is pinned) and, if none exists, fails *loudly* with
# an actionable message instead of an opaque ENOEXEC. ``DEERFLOW_LARK_BROKER_PYTHON``
# pins a specific interpreter for images that ship Python under a non-standard
# name.
#
# The launcher's path to the shim body is baked in at install time rather than
# derived from ``$0``: when the sandbox runs ``lark-cli`` off PATH, ``$0`` is the
# bare command name with no directory, so a sibling lookup would fail. The
# install dir is a stable, shared mount, so the absolute path is valid in both
# the init container that writes it and the sandbox that reads it.
#
# Both scripts are kept here as the single source of truth and mirrored by the
# broker image build via ``install_shim``, exactly like ``LARK_CLI_SANDBOX_LAUNCHER_SCRIPT``
# for Pattern A, so the image copies can never drift from the Gateway's.
LARK_BROKER_PYTHON_ENV = "DEERFLOW_LARK_BROKER_PYTHON"
LARK_CLI_BROKER_SHIM_FILENAME = "lark-cli-shim.py"
_LARK_CLI_BROKER_SHIM_PATH_PLACEHOLDER = "@@LARK_CLI_BROKER_SHIM_PATH@@"

LARK_CLI_BROKER_LAUNCHER_TEMPLATE = (
    "#!/bin/sh\n"
    "# DeerFlow lark-cli broker launcher (Pattern B). Resolves a Python 3\n"
    "# interpreter and execs the forwarding shim. Fails loudly (not with an opaque\n"
    "# ENOEXEC) when the sandbox image ships no python3. Uses only shell built-ins\n"
    "# so it still works when PATH is empty and DEERFLOW_LARK_BROKER_PYTHON pins\n"
    "# the interpreter.\n"
    "set -eu\n"
    'shim="' + _LARK_CLI_BROKER_SHIM_PATH_PLACEHOLDER + '"\n'
    'if [ -n "${DEERFLOW_LARK_BROKER_PYTHON:-}" ]; then\n'
    '  exec "$DEERFLOW_LARK_BROKER_PYTHON" "$shim" "$@"\n'
    "fi\n"
    "for _py in python3 python; do\n"
    '  if command -v "$_py" >/dev/null 2>&1; then\n'
    '    exec "$_py" "$shim" "$@"\n'
    "  fi\n"
    "done\n"
    'echo "lark-cli: broker mode needs a Python 3 interpreter but none was found;" >&2\n'
    'echo "          set DEERFLOW_LARK_BROKER_PYTHON to a python3 path in the sandbox image." >&2\n'
    "exit 127\n"
)


def render_launcher_script(shim_path: str) -> str:
    """Render the ``/bin/sh`` launcher with the shim body's absolute path baked in."""
    return LARK_CLI_BROKER_LAUNCHER_TEMPLATE.replace(_LARK_CLI_BROKER_SHIM_PATH_PLACEHOLDER, shim_path)


# The shim reads argv/stdin, POSTs to the broker, and replays the broker's
# stdout/stderr/exit code. On any transport failure it fails loudly and non-zero
# so a broker outage never looks like a successful lark-cli run. It is invoked as
# ``<python> lark-cli-shim.py <args...>`` by the launcher above (so it does not
# rely on its own shebang being resolvable), and stdin/argv pass straight through.
LARK_CLI_BROKER_SHIM_SCRIPT = r'''#!/usr/bin/env python3
"""DeerFlow lark-cli broker shim (Pattern B). Forwards argv/stdin to the broker.

Note: the broker runs lark-cli in the *sidecar's* working directory and cannot
see the sandbox filesystem, so cwd is intentionally not forwarded. Subcommands
that read/write files relative to the sandbox cwd are unsupported in broker mode.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

BROKER_URL = os.environ.get("DEERFLOW_LARK_BROKER_URL", "http://127.0.0.1:8788")


def _fail(message, code=127):
    sys.stderr.write("lark-cli: " + message + "\n")
    sys.exit(code)


def main():
    try:
        stdin_bytes = b"" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.buffer.read()
    except Exception:
        stdin_bytes = b""
    payload = json.dumps(
        {
            "args": sys.argv[1:],
            "stdin_b64": base64.b64encode(stdin_bytes).decode("ascii"),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        BROKER_URL.rstrip("/") + "/v1/exec",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:
            detail = ""
        _fail("broker rejected request (HTTP %d%s)" % (exc.code, ": " + detail if detail else ""))
    except (urllib.error.URLError, OSError) as exc:
        _fail("broker unreachable at %s (%s)" % (BROKER_URL, exc))
    except Exception as exc:  # noqa: BLE001
        _fail("broker call failed (%s)" % exc)
    sys.stdout.buffer.write(base64.b64decode(body.get("stdout_b64", "")))
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(base64.b64decode(body.get("stderr_b64", "")))
    sys.stderr.buffer.flush()
    sys.exit(int(body.get("exit_code", 1)))


if __name__ == "__main__":
    main()
'''


# ── Broker server ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BrokerConfig:
    """Runtime configuration for the broker sidecar."""

    lark_cli_path: str
    config_dir: str
    data_dir: str
    host: str = LARK_BROKER_DEFAULT_HOST
    port: int = LARK_BROKER_DEFAULT_PORT
    timeout_seconds: int = LARK_BROKER_DEFAULT_TIMEOUT_SECONDS
    # Opt-in denylist of ``lark-cli`` subcommand paths the broker refuses to run
    # (issue #4338 hardening). Each entry is a space-joined command prefix, e.g.
    # "config show" or "auth token", matched against the leading non-flag tokens
    # of the request. Narrows the command surface a prompt-injected agent can
    # reach — the broker already removes the credential *files*, but the full
    # command surface stays reachable unless a secret-dumping subcommand is denied
    # here. Empty by default (no behavior change).
    deny_subcommands: tuple[tuple[str, ...], ...] = ()

    def credential_env(self) -> dict[str, str]:
        """Env the broker injects into every lark-cli invocation.

        The client never supplies these — the broker owns the credential paths,
        so a sandbox process cannot point lark-cli at a different profile.
        """
        return {
            "LARKSUITE_CLI_CONFIG_DIR": self.config_dir,
            "LARKSUITE_CLI_DATA_DIR": self.data_dir,
            "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
            "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
        }


def parse_deny_subcommands(raw: str | None) -> tuple[tuple[str, ...], ...]:
    """Parse the comma-separated denylist env into command-prefix tuples.

    ``"config show, auth token"`` → ``(("config", "show"), ("auth", "token"))``.
    Blank/whitespace-only entries are dropped.
    """
    if not raw:
        return ()
    prefixes: list[tuple[str, ...]] = []
    for entry in raw.split(","):
        tokens = tuple(entry.split())
        if tokens:
            prefixes.append(tokens)
    return tuple(prefixes)


def _denied_subcommand(deny: tuple[tuple[str, ...], ...], args: list[str]) -> tuple[str, ...] | None:
    """Return the matched denylist prefix if ``args`` is a denied subcommand.

    Matches against the leading non-flag tokens (options and their values are
    skipped) so ``config --json show`` is still caught by a ``config show`` rule.
    """
    if not deny:
        return None
    positional = [token for token in args if not token.startswith("-")]
    for prefix in deny:
        if positional[: len(prefix)] == list(prefix):
            return prefix
    return None


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    truncated: bool


def run_lark_cli(config: BrokerConfig, args: list[str], stdin: bytes) -> ExecResult:
    """Run a single ``lark-cli`` invocation with broker-owned credentials.

    ``args`` is passed as an argv list with ``shell=False`` so a sandbox-supplied
    argument can never be shell-interpreted into a second command. A configured
    ``deny_subcommands`` prefix is refused before the binary is ever spawned.
    """
    denied = _denied_subcommand(config.deny_subcommands, args)
    if denied is not None:
        message = f"lark-cli: subcommand '{' '.join(denied)}' is disabled in broker mode\n"
        return ExecResult(126, b"", message.encode("utf-8"), False)
    env = {**os.environ, **config.credential_env()}
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, shell=False, fixed binary
            [config.lark_cli_path, *args],
            input=stdin,
            capture_output=True,
            timeout=config.timeout_seconds,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return ExecResult(124, b"", b"lark-cli: broker timed out\n", False)
    except FileNotFoundError:
        return ExecResult(127, b"", b"lark-cli: binary not found in broker\n", False)

    stdout, out_trunc = _cap(completed.stdout or b"")
    stderr, err_trunc = _cap(completed.stderr or b"")
    return ExecResult(completed.returncode, stdout, stderr, out_trunc or err_trunc)


def _cap(data: bytes) -> tuple[bytes, bool]:
    if len(data) <= LARK_BROKER_MAX_OUTPUT_BYTES:
        return data, False
    return data[:LARK_BROKER_MAX_OUTPUT_BYTES], True


def make_handler(config: BrokerConfig) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to ``config``.

    A bounded semaphore caps concurrency so a flood of sandbox calls cannot spawn
    unbounded ``lark-cli`` subprocesses.
    """
    semaphore = threading.BoundedSemaphore(LARK_BROKER_MAX_CONCURRENCY)

    class Handler(BaseHTTPRequestHandler):
        # Bound per-connection reads so a client that declares a large
        # Content-Length and never sends the body cannot park its thread forever
        # (ThreadingHTTPServer is one-thread-per-connection). stdlib reads this
        # to arm socket timeouts.
        timeout = LARK_BROKER_SOCKET_TIMEOUT_SECONDS

        # Quiet: default BaseHTTPRequestHandler logs to stderr per request.
        def log_message(self, *_args: Any) -> None:  # noqa: D401
            return

        def _send_json(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            if self.path.rstrip("/") == LARK_BROKER_HEALTH_PATH:
                self._send_json(200, {"ok": True})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            if self.path.rstrip("/") != LARK_BROKER_EXEC_PATH:
                self._send_json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(400, {"error": "bad content-length"})
                return
            if length <= 0 or length > LARK_BROKER_MAX_REQUEST_BYTES:
                self._send_json(413, {"error": "request too large"})
                return
            try:
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                args = request["args"]
                if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                    raise ValueError("args must be a list of strings")
                stdin = base64.b64decode(request.get("stdin_b64", "") or "")
            except Exception:  # noqa: BLE001 - untrusted client input
                self._send_json(400, {"error": "invalid request"})
                return

            if not semaphore.acquire(blocking=False):
                self._send_json(503, {"error": "broker busy"})
                return
            try:
                result = run_lark_cli(config, args, stdin)
            except Exception:  # noqa: BLE001 - keep the wire contract uniform
                # run_lark_cli already maps the expected failures (timeout,
                # missing binary) to ExecResults; anything else (OSError,
                # PermissionError, …) would otherwise close the connection with
                # no body and surface as an opaque transport error in the shim.
                # Return a structured 500 so the shim reports a meaningful error.
                logger.exception("lark-cli exec failed unexpectedly")
                self._send_json(500, {"error": "broker exec failed"})
                return
            finally:
                semaphore.release()

            self._send_json(
                200,
                {
                    "exit_code": result.exit_code,
                    "stdout_b64": base64.b64encode(result.stdout).decode("ascii"),
                    "stderr_b64": base64.b64encode(result.stderr).decode("ascii"),
                    "truncated": result.truncated,
                },
            )

    return Handler


def serve(config: BrokerConfig) -> ThreadingHTTPServer:
    """Start the broker HTTP server bound to loopback and return it."""
    if not shutil.which(config.lark_cli_path) and not os.path.isfile(config.lark_cli_path):
        logger.warning("lark-cli not found at %s; broker will report 127 for exec", config.lark_cli_path)
    server = ThreadingHTTPServer((config.host, config.port), make_handler(config))
    logger.info("lark-cli broker listening on %s:%d", config.host, config.port)
    return server


def install_shim(dest_dir: str, *, version: str | None = None) -> str:
    """Write the launcher + shim + runtime marker into the sandbox runtime dir.

    Called by the broker image's ``install-shim`` init-container mode. Produces
    the same ``bin/lark-cli`` + ``.deerflow-lark-cli-runtime.json`` layout Pattern
    A stages, but marked ``kind="shim"`` so the runtime validator knows the
    ``linux-*`` binaries are intentionally absent (the sidecar holds the real
    binary).

    Two files are written into ``bin/``: the executable-on-PATH ``lark-cli`` is a
    ``/bin/sh`` *launcher* that resolves a Python 3 interpreter and execs the
    ``lark-cli-shim.py`` *body* next to it. Splitting them keeps broker mode from
    silently failing with ENOEXEC on a sandbox image that has no ``python3`` (the
    launcher fails loudly with an actionable message instead). Both come from the
    in-process constants so the image copy can never drift from the Gateway's.
    """
    dest = os.path.abspath(dest_dir)
    bin_dir = os.path.join(dest, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    shim_body = os.path.join(bin_dir, LARK_CLI_BROKER_SHIM_FILENAME)
    with open(shim_body, "w", encoding="utf-8") as handle:
        handle.write(LARK_CLI_BROKER_SHIM_SCRIPT)
    os.chmod(shim_body, 0o755)
    launcher = os.path.join(bin_dir, "lark-cli")
    with open(launcher, "w", encoding="utf-8") as handle:
        handle.write(render_launcher_script(shim_body))
    os.chmod(launcher, 0o755)
    marker = os.path.join(dest, ".deerflow-lark-cli-runtime.json")
    with open(marker, "w", encoding="utf-8") as handle:
        json.dump({"version": version or "unknown", "kind": "shim"}, handle)
    return launcher


def _config_from_env() -> BrokerConfig:
    return BrokerConfig(
        lark_cli_path=os.environ.get("DEERFLOW_LARK_BROKER_CLI", "lark-cli"),
        config_dir=os.environ.get("LARKSUITE_CLI_CONFIG_DIR", "/var/lark/config"),
        data_dir=os.environ.get("LARKSUITE_CLI_DATA_DIR", "/var/lark/data"),
        host=os.environ.get("DEERFLOW_LARK_BROKER_HOST", LARK_BROKER_DEFAULT_HOST),
        port=int(os.environ.get("DEERFLOW_LARK_BROKER_PORT", str(LARK_BROKER_DEFAULT_PORT))),
        timeout_seconds=int(os.environ.get("DEERFLOW_LARK_BROKER_TIMEOUT", str(LARK_BROKER_DEFAULT_TIMEOUT_SECONDS))),
        deny_subcommands=parse_deny_subcommands(os.environ.get(LARK_BROKER_DENY_SUBCOMMANDS_ENV)),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    argv = sys.argv[1:]
    if argv and argv[0] == "install-shim":
        dest = argv[1] if len(argv) > 1 else os.environ.get("LARK_CLI_RUNTIME_DEST", "/mnt/integrations/lark-cli/runtime")
        launcher = install_shim(dest, version=os.environ.get("LARK_CLI_VERSION"))
        logger.info("Installed lark-cli broker shim at %s", launcher)
        return
    server = serve(_config_from_env())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
