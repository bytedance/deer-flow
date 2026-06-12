"""ACP (Agent Client Protocol) hand-rolled JSON-RPC smoke test against
`claude-agent-acp`.

What it does
------------
Speaks raw JSON-RPC line-by-line over stdio to the `claude-agent-acp`
subprocess and walks the minimum handshake:

    1. initialize       -- protocol version + client capabilities
    2. session/new      -- open a session with cwd=/tmp and mcpServers=[]
    3. session/prompt   -- send a 3-word "say hi" prompt and print the reply

Notifications (e.g. `session/update`) are skipped while we poll for the
response whose `id` matches our request. STDERR is drained at the end so any
handshake failure (missing binary, auth error, bad protocol version, etc.)
is visible.

Use this when DeerFlow's `invoke_acp_agent` tool fails (permission denied,
session times out, agent never responds) and you want to isolate whether the
problem is in DeerFlow's wrapper or in `claude-agent-acp` itself.

How to run -- inside the container
----------------------------------
`claude-agent-acp` should already be on PATH and `CLAUDE_CODE_EXECUTABLE`
should point at /usr/local/bin/claude (per `docker/claude/` bundle).

Option A -- exec into the gateway container directly:

    docker exec -it <gateway-container> bash
    python3 /app/docx/integration/claude-code/claude-acp-diag.py

Option B -- copy the script in and run it:

    docker cp docx/integration/claude-code/claude-acp-diag.py \
        <gateway-container>:/tmp/diag.py
    docker exec -it <gateway-container> python3 /tmp/diag.py

How to run -- on the host (only if claude-agent-acp is installed locally)
------------------------------------------------------------------------

    python3 docx/integration/claude-code/claude-acp-diag.py
"""

import json
import subprocess
import sys
import time


def call(p: subprocess.Popen, method: str, params: dict, mid: int) -> dict | None:
    """Send a JSON-RPC request and read until we get the response with our id."""
    msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}
    p.stdin.write(json.dumps(msg) + "\n")
    p.stdin.flush()
    while True:
        line = p.stdout.readline()
        if not line:
            print(f"[{method}] EOF on stdout")
            try:
                print("STDERR-AT-EOF:", p.stderr.read())
            except Exception:
                pass
            return None
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            print(f"[{method}] non-JSON: {line!r}")
            continue
        if obj.get("id") == mid:
            return obj
        # else: notification (e.g. session/update) -- ignore while polling


def show(label: str, r: dict | None) -> None:
    print(f"=== {label} ===")
    if r is None:
        print("NO RESPONSE (subprocess died)")
    else:
        print(json.dumps(r, indent=2)[:1500])
    print()


def main() -> int:
    p = subprocess.Popen(
        ["claude-agent-acp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    try:
        # 1. initialize
        show(
            "initialize",
            call(
                p,
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {},
                    "clientInfo": {"name": "diag", "title": "Diag", "version": "0"},
                },
                1,
            ),
        )

        # 2. session/new  (mcpServers must be a list, even if empty)
        r_new = call(
            p,
            "session/new",
            {"cwd": "/tmp", "mcpServers": []},
            2,
        )
        show("session/new", r_new)

        if r_new and "result" in r_new:
            sid = r_new["result"].get("sessionId")
            print(f"sessionId = {sid}\n")

            # 3. session/prompt
            show(
                "session/prompt",
                call(
                    p,
                    "session/prompt",
                    {
                        "sessionId": sid,
                        "prompt": [{"type": "text", "text": "say hi in 3 words"}],
                    },
                    3,
                ),
            )
    finally:
        p.terminate()
        try:
            time.sleep(0.3)
        except Exception:
            pass
        try:
            leftover = p.stderr.read()
            if leftover:
                print("=== FINAL STDERR ===")
                print(leftover)
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
