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

# Arch-dispatch is not needed for the shim (it is pure Python), but the shim is
# kept in one place and mirrored by the broker image build with a drift-guard
# test, exactly like LARK_CLI_SANDBOX_LAUNCHER_SCRIPT for Pattern A.
#
# The shim reads argv/stdin, POSTs to the broker, and replays the broker's
# stdout/stderr/exit code. On any transport failure it fails loudly and non-zero
# so a broker outage never looks like a successful lark-cli run.
LARK_CLI_BROKER_SHIM_SCRIPT = r'''#!/usr/bin/env python3
"""DeerFlow lark-cli broker shim (Pattern B). Forwards argv/stdin to the broker."""
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
            "cwd": os.getcwd(),
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
        _fail("broker rejected request (HTTP %d)" % exc.code)
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


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    truncated: bool


def run_lark_cli(config: BrokerConfig, args: list[str], stdin: bytes) -> ExecResult:
    """Run a single ``lark-cli`` invocation with broker-owned credentials.

    ``args`` is passed as an argv list with ``shell=False`` so a sandbox-supplied
    argument can never be shell-interpreted into a second command.
    """
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
    """Write the shim + runtime marker into the sandbox runtime dir.

    Called by the broker image's ``install-shim`` init-container mode. Produces
    the same ``bin/lark-cli`` + ``.deerflow-lark-cli-runtime.json`` layout Pattern
    A stages, but marked ``kind="shim"`` so the runtime validator knows the
    ``linux-*`` binaries are intentionally absent (the sidecar holds the real
    binary). Sourcing the shim from the in-process constant means the image can
    never drift from the Gateway's copy.
    """
    dest = os.path.abspath(dest_dir)
    bin_dir = os.path.join(dest, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    launcher = os.path.join(bin_dir, "lark-cli")
    with open(launcher, "w", encoding="utf-8") as handle:
        handle.write(LARK_CLI_BROKER_SHIM_SCRIPT)
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
