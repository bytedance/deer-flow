#!/usr/bin/env python3
"""Build the full native Next app and probe SSR redirects in Shanghai CI.

Run inside the owned Linux CI container, never on the developer workstation.
The loopback Gateway below is a synthetic auth fixture, not JWT/business proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN = "native-next-ssr-fixture"
USER = {
    "id": "alice",
    "email": "alice@example.test",
    "system_role": "user",
    "needs_setup": False,
}
TEAM = "22222222-2222-2222-2222-222222222222"
GATEWAY_PORT = 8001
NEXT_PORT = 3000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RefreshTarget(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag != "meta" or (values.get("http-equiv") or "").lower() != "refresh":
            return
        content = values.get("content") or ""
        marker = content.lower().find("url=")
        if marker >= 0:
            self.targets.append(content[marker + 4 :].strip().strip("\"'"))


def production_digest(root: Path) -> str:
    frontend = root / "frontend"
    files = set()
    for base in [
        frontend / "src",
        frontend / "content",
        frontend / "public",
        root / "contracts",
    ]:
        if base.exists():
            files.update(
                p for p in base.rglob("*") if p.is_file() and not p.is_symlink()
            )
    files.update(
        p for p in frontend.iterdir() if p.is_file() and p.suffix not in {".md", ".txt"}
    )
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def stop(process: subprocess.Popen | None):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--compiled-archive", type=Path)
    parser.add_argument("--compiled-receipt", type=Path)
    parser.add_argument("--check-boundaries", action="store_true")
    args = parser.parse_args()
    if sys.platform != "linux" or os.environ.get("DEERFLOW_CLOUD_FIXTURE") != "1":
        parser.error(
            "Run only in the owned Shanghai Linux CI container with DEERFLOW_CLOUD_FIXTURE=1"
        )
    if bool(args.compiled_archive) != bool(args.compiled_receipt):
        parser.error("Compiled archive and its verified receipt are required together")
    root = args.root.resolve()
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    frontend = root / "frontend"
    pnpm = [sys.executable, str(root / "scripts/pnpm.py")]
    requests: list[dict] = []
    result = {
        "status": "failed",
        "scope": "full native Next production build and HTTP SSR against synthetic loopback Gateway auth; not real JWT/workspace/business acceptance",
        "models_called": False,
        "artifact_usage": "compiled Next test fixture only; synthetic Gateway destination, not a release artifact",
        "gateway_port": GATEWAY_PORT,
        "next_port": NEXT_PORT,
        "production_inputs_sha256": production_digest(root),
        "node": subprocess.check_output(["node", "--version"], text=True).strip(),
        "next": json.loads((frontend / "node_modules/next/package.json").read_text())[
            "version"
        ],
        "rows": [],
        "boundaries": {},
        "build_reused": False,
        "gateway_requests": requests,
        "failure": None,
    }

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            cookie = SimpleCookie()
            cookie.load(self.headers.get("Cookie", ""))
            accepted = (
                cookie.get("access_token") is not None
                and cookie["access_token"].value == TOKEN
            )
            path = urllib.parse.urlsplit(self.path).path
            requests.append(
                {
                    "path": path,
                    "cookie_present": "access_token" in cookie,
                    "fixture_session_accepted": accepted,
                }
            )
            if path == "/api/v1/auth/setup-status":
                status, body = 200, {"needs_setup": False}
            elif path == "/api/v1/auth/me":
                status, body = (
                    (200, USER) if accepted else (401, {"detail": "not_authenticated"})
                )
            elif path == "/api/features":
                status, body = (
                    200,
                    {"workspaces": {"enabled": False, "available": False}},
                )
            else:
                status, body = 404, {"detail": "not_in_auth_fixture"}
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    gateway = ThreadingHTTPServer(("127.0.0.1", GATEWAY_PORT), Gateway)
    thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    env = dict(os.environ)
    env.update(
        {
            "NODE_ENV": "production",
            "NEXT_TELEMETRY_DISABLED": "1",
            "DEER_FLOW_BUILD_MEMORY_OPTIMIZATIONS": "1",
            "SKIP_ENV_VALIDATION": "1",
            "DEER_FLOW_TRUSTED_ORIGINS": f"http://127.0.0.1:{NEXT_PORT}",
            "DEER_FLOW_INTERNAL_GATEWAY_BASE_URL": f"http://127.0.0.1:{gateway.server_port}",
        }
    )
    for key in [
        "DEER_FLOW_AUTH_DISABLED",
        "NEXT_PUBLIC_STATIC_WEBSITE_ONLY",
        "NEXT_PUBLIC_BACKEND_BASE_URL",
        "NEXT_PUBLIC_LANGGRAPH_BASE_URL",
        "NEXT_CONFIG_BUILD_OUTPUT",
    ]:
        env.pop(key, None)
    build = None
    server = None
    try:
        if args.compiled_archive:
            receipt = json.loads(args.compiled_receipt.read_text())
            for key in [
                "production_inputs_sha256",
                "node",
                "next",
                "gateway_port",
                "next_port",
            ]:
                if receipt.get(key) != result[key]:
                    raise ValueError("Compiled artifact does not match current " + key)
            compiled = args.compiled_archive
            if receipt.get("status") != "main_passed" or hashlib.sha256(
                compiled.read_bytes()
            ).hexdigest() != receipt.get("compiled_archive_sha256"):
                raise ValueError("Compiled artifact lacks a matching passed receipt")
            with tarfile.open(compiled) as archive:
                members = archive.getmembers()
                if any(
                    not m.isfile()
                    or Path(m.name).is_absolute()
                    or ".." in Path(m.name).parts
                    or not m.name.startswith(".next/")
                    for m in members
                ):
                    raise ValueError("Unexpected compiled artifact entry")
                archive.extractall(frontend, members=members, filter="data")
            if (frontend / ".next/BUILD_ID").read_text().strip() != receipt.get(
                "build_id"
            ):
                raise ValueError("Restored BUILD_ID does not match receipt")
            result.update(
                build_reused=True,
                build_exit=0,
                build_seconds=0,
                build_id=receipt["build_id"],
            )
            (evidence / "compiled-build-receipt.json").write_text(
                json.dumps(receipt, indent=2) + "\n"
            )
        else:
            started = time.monotonic()
            with (evidence / "build.log").open("w") as log:
                build = subprocess.Popen(
                    [*pnpm, "build", "--webpack"],
                    cwd=frontend,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                result["build_exit"] = build.wait(timeout=1200)
            result["build_seconds"] = round(time.monotonic() - started, 2)
            if result["build_exit"] != 0:
                raise RuntimeError("Native Next build failed; inspect build.log")
            result["build_id"] = (frontend / ".next/BUILD_ID").read_text().strip()
            # This is a test artifact: its Gateway destination is the synthetic service.
            compiled = evidence / "next-output.tar.gz"
            with tarfile.open(compiled, "w:gz") as archive:
                for path in sorted((frontend / ".next").rglob("*")):
                    relative = path.relative_to(frontend)
                    if (
                        path.is_file()
                        and not path.is_symlink()
                        and "cache" not in relative.parts[1:2]
                    ):
                        archive.add(path, arcname=str(relative), recursive=False)
        result["compiled_archive_sha256"] = hashlib.sha256(
            compiled.read_bytes()
        ).hexdigest()
        result["compiled_archive_bytes"] = compiled.stat().st_size
        port = NEXT_PORT
        with (evidence / "server.log").open("w") as log:
            server = subprocess.Popen(
                [*pnpm, "start", "--hostname", "127.0.0.1", "--port", str(port)],
                cwd=frontend,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            deadline = time.monotonic() + 60
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Native Next server exited; inspect server.log")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "Native Next server did not listen"
                        ) from None
                    time.sleep(0.25)
            origin = f"http://127.0.0.1:{port}"
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), NoRedirect()
            )

            def read_redirect(path: str, authenticated: bool, extra_headers=None):
                headers = {"Accept": "text/html", **(extra_headers or {})}
                if authenticated:
                    headers["Cookie"] = "access_token=" + TOKEN
                request = urllib.request.Request(origin + path, headers=headers)
                try:
                    response = opener.open(request, timeout=30)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    body = response.read(2 * 1024 * 1024)
                    if any(
                        name.lower()
                        in {
                            "cookie",
                            "x-deerflow-request-route",
                            "x-middleware-override-headers",
                        }
                        or name.lower().startswith("x-middleware-request-")
                        for name in response.headers
                    ):
                        raise AssertionError(
                            "Internal request metadata leaked into the HTTP response"
                        )
                    location = response.headers.get("Location")
                    kind = "location"
                    if not location and response.status == 200:
                        meta = RefreshTarget()
                        meta.feed(body.decode("utf-8", errors="replace"))
                        if len(meta.targets) == 1:
                            location = meta.targets[0]
                            kind = "streaming_meta"
                    if response.status not in {200, 302, 303, 307, 308} or not location:
                        raise AssertionError(
                            f"Expected Next redirect, got {response.status}"
                        )
                    destination = urllib.parse.urlsplit(
                        urllib.parse.urljoin(origin, location)
                    )
                    if destination.scheme + "://" + destination.netloc != origin:
                        raise AssertionError("Next redirect escaped fixture origin")
                    target = destination.path + (
                        "?" + destination.query if destination.query else ""
                    )
                    result["rows"].append(
                        {
                            "request": path,
                            "authenticated": authenticated,
                            "status": response.status,
                            "redirect_kind": kind,
                            "target": target,
                            "body_bytes": len(body),
                        }
                    )
                    return target

            target = f"/workspace/chats/private?workspace_id={TEAM}&tab=files"
            login = read_redirect(target, False)
            login_url = urllib.parse.urlsplit(login)
            if login_url.path != "/login" or urllib.parse.parse_qs(login_url.query).get(
                "next"
            ) != [target]:
                raise AssertionError(
                    "Unauthenticated native Next lost workspace/resource return URI"
                )
            returned = read_redirect(
                "/login?" + urllib.parse.urlencode({"next": target}), True
            )
            if returned != target:
                raise AssertionError(
                    "Authenticated native Next login entry lost requested URI"
                )
            if args.check_boundaries:
                forged = read_redirect(
                    target,
                    False,
                    {
                        "x-deerflow-request-route": "/workspace/chats/forged?workspace_id=11111111-1111-1111-1111-111111111111"
                    },
                )
                if urllib.parse.parse_qs(urllib.parse.urlsplit(forged).query).get(
                    "next"
                ) != [target]:
                    raise AssertionError(
                        "Client header retargeted the native SSR return"
                    )
                result["boundaries"]["forged_header_overwritten"] = True
                unsafe = read_redirect(
                    "/login?"
                    + urllib.parse.urlencode(
                        {"next": "https://outside.invalid/workspace"}
                    ),
                    True,
                )
                if unsafe != "/workspace":
                    raise AssertionError(
                        "Unsafe next did not retain native local fallback"
                    )
                result["boundaries"]["unsafe_next_stays_local"] = True
                demo_source = (frontend / "src/core/threads/static-demo.ts").read_text()
                demo = re.search(
                    r'export const DEMO_THREAD_IDS = \[\s*"([^"]+)"', demo_source
                )
                if not demo:
                    raise AssertionError(
                        "Native generated-demo route fixture not found"
                    )
                generated_target = (
                    f"/workspace/chats/{demo.group(1)}?workspace_id={TEAM}"
                )
                generated_login = read_redirect(generated_target, False)
                if urllib.parse.parse_qs(
                    urllib.parse.urlsplit(generated_login).query
                ).get("next") != [generated_target]:
                    raise AssertionError(
                        "Generated native route lost request-dependent auth return"
                    )
                result["boundaries"]["generated_route_keeps_auth_return"] = True
                result["boundaries"]["no_request_header_leak"] = True
            result["status"] = "main_passed"
    except Exception as error:
        result["failure"] = f"{type(error).__name__}: {error}"
    finally:
        stop(build)
        stop(server)
        gateway.shutdown()
        gateway.server_close()
        thread.join(timeout=5)
        (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "failure": result["failure"],
                "evidence": str(evidence / "result.json"),
            }
        )
    )
    return 0 if result["status"] == "main_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
