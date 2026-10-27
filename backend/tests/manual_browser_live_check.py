"""Live end-to-end verification for the agentic browser tools.

NOT a unit test. Run manually with DEEPSEEK_API_KEY in the environment:

    DEEPSEEK_API_KEY=sk-... PYTHONPATH=. uv run python tests/manual_browser_live_check.py

It:
  1. serves a tiny local HTML form,
  2. builds an isolated DeerFlow config (DeepSeek model + browser tool group),
  3. runs a real agent turn that must navigate, type, submit, and read the result,
  4. asserts the agent-visible tool trace shows the browser loop actually ran.
"""

from __future__ import annotations

import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

FORM_PAGE = """<!doctype html><html><head><title>DeerFlow Browser Test</title></head>
<body>
<h1>Sign-in demo</h1>
<form method="GET" action="/welcome">
  <input type="text" name="username" placeholder="Username">
  <button type="submit">Sign in</button>
</form>
</body></html>"""


def _welcome_page(username: str) -> str:
    return f"""<!doctype html><html><head><title>Welcome</title></head>
<body><h1>Welcome, {username}!</h1><p>SECRET-TOKEN-4917</p></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence server logs
        pass

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(self.path)
        if parsed.path.startswith("/welcome"):
            qs = parse_qs(parsed.query)
            username = (qs.get("username") or ["friend"])[0]
            body = _welcome_page(username)
        else:
            body = FORM_PAGE
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _start_server() -> tuple[HTTPServer, int]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def _write_config(tmp: Path) -> Path:
    config = f"""
config_version: 1
data_dir: {tmp / "data"}

models:
  - name: deepseek-chat
    display_name: DeepSeek Chat
    use: deerflow.models.patched_deepseek:PatchedChatDeepSeek
    model: deepseek-chat
    api_key: $DEEPSEEK_API_KEY
    timeout: 120.0
    max_retries: 2
    max_tokens: 4096

sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider

tool_groups:
  - name: browser

tools:
  - name: browser_navigate
    group: browser
    use: deerflow.community.browser_automation.tools:browser_navigate_tool
    headless: true
    allow_private_addresses: true
  - name: browser_snapshot
    group: browser
    use: deerflow.community.browser_automation.tools:browser_snapshot_tool
  - name: browser_click
    group: browser
    use: deerflow.community.browser_automation.tools:browser_click_tool
  - name: browser_type
    group: browser
    use: deerflow.community.browser_automation.tools:browser_type_tool
  - name: browser_get_text
    group: browser
    use: deerflow.community.browser_automation.tools:browser_get_text_tool
  - name: browser_close
    group: browser
    use: deerflow.community.browser_automation.tools:browser_close_tool

memory:
  enabled: false

title:
  enabled: false
"""
    path = tmp / "config.yaml"
    path.write_text(config)
    return path


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("SKIP: DEEPSEEK_API_KEY not set")
        return 0

    server, port = _start_server()
    base = f"http://127.0.0.1:{port}/"
    tmpdir = Path(tempfile.mkdtemp(prefix="deerflow-browser-live-"))
    try:
        from deerflow.client import DeerFlowClient

        config_path = _write_config(tmpdir)
        # Make config resolution deterministic: get_available_tools() re-resolves
        # via get_app_config(), which would otherwise pick up a project-root
        # config.yaml. DEER_FLOW_CONFIG_PATH is resolution priority #2.
        os.environ["DEER_FLOW_CONFIG_PATH"] = str(config_path)
        client = DeerFlowClient(config_path=str(config_path))

        prompt = (
            f"Use the browser tools to complete this task. "
            f"1) Navigate to {base} 2) type the username 'deerbot' into the username field "
            f"3) click the Sign in button 4) read the resulting page's text. "
            f"Then tell me the exact SECRET token shown on the welcome page."
        )

        tool_calls: list[str] = []
        final_text = ""
        for event in client.stream(prompt, thread_id="browser-live-check"):
            if event.type == "messages-tuple":
                data = event.data or {}
                if data.get("type") == "tool":
                    name = data.get("name") or ""
                    if name.startswith("browser_"):
                        tool_calls.append(name)
                elif data.get("type") == "ai":
                    final_text += data.get("content") or ""

        print("Browser tool calls observed:", tool_calls)
        print("Final answer:\n", final_text.strip()[:1000])

        assert "browser_navigate" in tool_calls, "agent never navigated"
        assert any(t in tool_calls for t in ("browser_type", "browser_click")), "agent never interacted"
        assert "SECRET-TOKEN-4917" in final_text, "agent did not read the post-submit page content"
        print("\nLIVE CHECK PASSED")
        return 0
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
