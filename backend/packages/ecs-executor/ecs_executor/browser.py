"""Bounded outbound control transport for the actual native browser routes.

Credentials and browser frames live only in TLS transport/process memory. The
worker invokes its existing ASGI app; there is no browser runner or proxy URL.
"""

import asyncio
import base64
import contextlib
import hmac
import ipaddress
import json
import uuid
from urllib.parse import quote, urlsplit

from fastapi import HTTPException
from starlette.routing import WebSocketRoute
from websockets.asyncio.client import connect

from deerflow.community.browser_automation.session import BrowserSessionScope, browser_session_key, browser_session_scope, configure_browser_session_manager, get_browser_session_manager
from ecs_executor.dispatch import PROTOCOL, WORKER_VERSION
from ecs_executor.scope import mint_execution_scope, verify_execution_scope

MAX_WIRE = 2 * 1024 * 1024
MAX_INPUT = 32768
MAX_CHANNELS = 8
HEADER_NAMES = {"cookie", "authorization", "host", "origin", "x-csrf-token", "content-type", "x-forwarded-host"}


def worker_tunnel_url(value, fixture_loopback):
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError("Browser tunnel requires a fixed control origin")
    if parsed.scheme == "https":
        return "wss://" + parsed.netloc
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = False
    if parsed.scheme == "http" and fixture_loopback is True and loopback:
        return "ws://" + parsed.netloc
    raise ValueError("Browser tunnel requires TLS (explicit literal-loopback fixture exception only)")


def forwarded_headers(headers):
    result = [[key.decode("latin1").lower(), value.decode("latin1")] for key, value in headers.raw if key.decode("latin1").lower() in HEADER_NAMES]
    if len(json.dumps(result)) > MAX_INPUT:
        raise ValueError("Browser authentication headers exceed bound")
    return result


def verify_browser_operation(operation, args, token, *, secret, node, owner):
    if operation not in {"navigate", "stream"} or args.get("owner") != owner:
        raise ValueError("Browser operation denied")
    claims = verify_execution_scope(token, secret=secret.encode(), authenticated_user_id=args["user_id"], arguments=args, expected_audience=node, expected_operation="browser_" + operation)
    if any(claims[key] != args[key] for key in ("user_id", "thread_id", "incarnation")) or claims["run_id"] != args["id"]:
        raise ValueError("Browser identity denied")
    if len(json.dumps(args)) > MAX_INPUT or set(args) != {"id", "owner", "user_id", "thread_id", "incarnation", "headers", "query", "scheme", "url"}:
        raise ValueError("Browser arguments denied")
    if not isinstance(args["headers"], list) or any(not isinstance(pair, list) or len(pair) != 2 or pair[0] not in HEADER_NAMES or not isinstance(pair[1], str) for pair in args["headers"]):
        raise ValueError("Browser headers denied")
    if args["scheme"] not in {"http", "https"} or not isinstance(args["query"], str) or not isinstance(args["url"], str):
        raise ValueError("Browser arguments denied")
    return BrowserSessionScope(args["user_id"], args["thread_id"], args["incarnation"])


def _encode_event(event):
    return {**event, **({"bytes": base64.b64encode(event["bytes"]).decode("ascii")} if isinstance(event.get("bytes"), bytes) else {})}


def _decode_event(event):
    return {**event, **({"bytes": base64.b64decode(event["bytes"], validate=True)} if event.get("bytes") is not None else {})}


class Tunnel:
    def __init__(self, websocket, owner):
        self.websocket, self.owner = websocket, owner
        self.channels = {}
        self.lock = asyncio.Lock()
        self.closed = False

    async def send(self, value):
        raw = json.dumps(value, separators=(",", ":"))
        if len(raw.encode()) > MAX_WIRE:
            raise ValueError("Browser frame exceeds transport bound")
        async with self.lock:
            async with asyncio.timeout(10):
                if hasattr(self.websocket, "send_text"):
                    await self.websocket.send_text(raw)
                else:
                    await self.websocket.send(raw)

    def channel(self, request_id):
        if self.closed or len(self.channels) >= MAX_CHANNELS:
            raise HTTPException(503, "Browser worker transport unavailable")
        queue = asyncio.Queue(maxsize=8)
        self.channels[request_id] = queue
        return queue

    async def shutdown(self):
        self.closed = True
        for queue in self.channels.values():
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait({"event": {"type": "websocket.close", "code": 1011}})


class NativeBrowserControl:
    def __init__(self, native_config, settings):
        self.config = json.loads(json.dumps(native_config))
        self.settings = dict(settings)
        self.role = native_config.get("role")
        self.app = self.host = None
        self.tunnels = {}
        self.scopes = {}
        self.operations = {}
        self.operation_scopes = {}
        self.execution_scopes = {}
        self.task = self.watcher = None
        self.closing = False
        self.fixture_loopback = settings.get("test_only_allow_loopback_plaintext") is True

    def validate_startup(self, config):
        import os

        from ecs_executor.nodes import Node
        from ecs_executor.scope import _secret

        if self.role not in {"central", "worker"} or not config.deployment.multi_instance or config.database.backend != "postgres" or not config.run_ownership.heartbeat_enabled or config.run_events.backend != "db":
            raise ValueError("Browser affinity requires enabled native multi-instance host")
        tool = config.get_tool_config("browser_navigate")
        if tool is None or (tool.model_extra or {}).get("cdp_url"):
            raise ValueError("Bounded native browser requires configured guarded Playwright without CDP")
        if self.role == "central":
            node_id = self.config["native_node"]
            node = Node.model_validate(self.config["nodes"][node_id])
            if node.max_concurrency != 1 or "C" not in node.kinds or node.resident_cpu_millis < 1500 or node.resident_memory_mib < 2048:
                raise ValueError("Browser affinity requires the fixed serial native worker budget")
            _secret(os.environ[self.config["worker_credential_env"][node_id]].encode())
        else:
            worker_tunnel_url(self.config["executor_url"], self.fixture_loopback)
            _secret(os.environ[self.config["credential_env"]].encode())
        configure_browser_session_manager(max_sessions=1, strict_physical_capacity=True)

    async def bind(self, app, native_host):
        self.app, self.host = app, native_host
        native_host.browser_control = self
        if self.role == "central":
            app.router.routes.insert(0, WebSocketRoute("/api/native-workers/{node}/browser-control", self.accept_tunnel))
        else:
            self.task = asyncio.create_task(self.run_tunnel())
            self.watcher = asyncio.create_task(self.watch_sessions())

    async def _current_scope(self, thread_id, user_id):
        record = await self.app.state.thread_store.get(thread_id, user_id=user_id)
        if record is None or record.get("user_id") != user_id or not record.get("incarnation"):
            raise HTTPException(404, "Browser thread not found")
        return BrowserSessionScope(user_id, thread_id, record["incarnation"])

    async def execution_scope(self, native):
        scope = await self._current_scope(native["thread_id"], native["user_id"])
        if scope.incarnation != native["incarnation"] or self.role != "worker":
            raise ValueError("Native browser execution scope changed")
        self._remember_scope(scope)
        self.execution_scopes[scope.key] = None

        @contextlib.contextmanager
        def binding():
            attached = False

            def attach(task):
                nonlocal attached
                attached = True
                self.execution_scopes[scope.key] = task

                def completed(done):
                    if self.execution_scopes.get(scope.key) is done:
                        self.execution_scopes.pop(scope.key, None)
                    self._prune_scopes()

                task.add_done_callback(completed)

            try:
                with browser_session_scope(scope):
                    yield attach
            finally:
                if not attached:
                    self.execution_scopes.pop(scope.key, None)
                self._prune_scopes()

        return binding()

    async def session_scope(self, thread_id, user_id):
        scope = await self._current_scope(thread_id, user_id)
        if self.role == "worker":
            # Only verified native task/ASGI operation binders can select scope.
            if browser_session_key(thread_id) != scope.key:
                raise HTTPException(403, "Browser worker requires scoped control")
            self._remember_scope(scope)
        return scope

    async def _placement(self, thread_id, user_id):
        from ecs_executor.agent_dispatch import _affinity

        scope = await self._current_scope(thread_id, user_id)
        node = self.config["native_node"]
        placed = await asyncio.to_thread(_affinity, self.host.pool.store, user_id, thread_id, scope.incarnation, node_id=node)
        if placed != node or node not in self.tunnels or self.tunnels[node].closed:
            raise HTTPException(503, "Browser worker transport unavailable")
        return scope, node, self.tunnels[node]

    async def _open(self, operation, request, thread_id, user_id, *, url=""):
        scope, node, tunnel = await self._placement(thread_id, user_id)
        request_id = uuid.uuid4().hex
        args = {
            "id": request_id,
            "owner": tunnel.owner,
            "user_id": user_id,
            "thread_id": thread_id,
            "incarnation": scope.incarnation,
            "headers": forwarded_headers(request.headers),
            "query": request.scope.get("query_string", b"").decode("ascii"),
            "scheme": "https" if request.scope["scheme"] in {"https", "wss"} else "http",
            "url": url,
        }
        token = mint_execution_scope(
            secret=self.host.credentials[node].encode(), audience=node, user_id=user_id, thread_id=thread_id, incarnation=scope.incarnation, run_id=request_id, operation="browser_" + operation, arguments=args, ttl_seconds=300
        )
        queue = tunnel.channel(request_id)
        try:
            await tunnel.send({"kind": "open", "operation": operation, "args": args, "capability": token})
        except BaseException:
            tunnel.channels.pop(request_id, None)
            raise
        return request_id, queue, tunnel

    async def navigate(self, request, thread_id, url):
        if self.role == "worker":
            return None
        user_id = str(request.state.auth.user.id)
        request_id, queue, tunnel = await self._open("navigate", request, thread_id, user_id, url=url)
        try:
            async with asyncio.timeout(60):
                result = await queue.get()
            if result.get("kind") != "http":
                raise HTTPException(503, "Browser transport disconnected; operation outcome unknown")
            if result["status"] != 200:
                if result["status"] == 503 and result.get("body") == {"detail": "Browser operation outcome unknown"}:
                    raise HTTPException(503, "Browser operation outcome unknown")
                raise HTTPException(result["status"], "Native worker browser operation rejected")
            return result["body"]
        except TimeoutError:
            raise HTTPException(504, "Browser operation timed out; outcome unknown") from None
        finally:
            tunnel.channels.pop(request_id, None)
            with contextlib.suppress(Exception):
                await tunnel.send({"kind": "close", "id": request_id})

    async def stream(self, websocket, thread_id, user_id):
        if self.role == "worker":
            return False
        request_id, queue, tunnel = await self._open("stream", websocket, thread_id, user_id)
        accepted = False
        reader = output = None
        ready = asyncio.Event()

        async def inputs():
            await ready.wait()
            while True:
                event = await websocket.receive()
                if event["type"] == "websocket.disconnect":
                    return
                if event.get("bytes") is not None or len((event.get("text") or "").encode()) > MAX_INPUT:
                    await websocket.close(1009)
                    return
                await tunnel.send({"kind": "input", "id": request_id, "event": event})

        async def outputs():
            nonlocal accepted
            while True:
                value = await queue.get()
                event = _decode_event(value["event"])
                if event["type"] == "websocket.accept":
                    await websocket.accept()
                    accepted = True
                    ready.set()
                elif event["type"] == "websocket.close":
                    await websocket.close(event.get("code", 1000))
                    return
                elif event["type"] == "websocket.send" and accepted:
                    await websocket.send(event)
                else:
                    raise ValueError("Browser stream protocol denied")

        try:
            async with asyncio.timeout(300):
                output = asyncio.create_task(outputs())
                reader = asyncio.create_task(inputs())
                done, pending = await asyncio.wait([output, reader], return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    task.result()
        finally:
            for task in (reader, output):
                if task is not None:
                    task.cancel()
            await asyncio.gather(*(task for task in (reader, output) if task is not None), return_exceptions=True)
            tunnel.channels.pop(request_id, None)
            with contextlib.suppress(Exception):
                await tunnel.send({"kind": "close", "id": request_id})
        return True

    async def accept_tunnel(self, websocket):
        node = websocket.path_params["node"]
        secret = self.host.credentials.get(node)
        if node != self.config["native_node"] or not secret or not hmac.compare_digest(websocket.headers.get("authorization", ""), "Bearer " + secret):
            await websocket.close(4403)
            return
        scheme = websocket.scope["scheme"]
        local_client = websocket.client is not None and websocket.client.host in {"127.0.0.1", "::1"}
        if scheme != "wss" and not (self.fixture_loopback and local_client):
            await websocket.close(4403)
            return
        if node in self.tunnels:
            await websocket.close(4409)
            return
        await websocket.accept()
        tunnel = None
        try:
            async with asyncio.timeout(10):
                raw = await websocket.receive_text()
            if len(raw.encode()) > MAX_INPUT:
                raise ValueError("Browser worker hello too large")
            hello = json.loads(raw)
            if (
                hello.get("protocol") != PROTOCOL
                or hello.get("worker_version") != self.host.pool.nodes[node].worker_version
                or hello.get("mount_id") != self.host.mount_id
                or not isinstance(hello.get("owner"), str)
                or not 1 <= len(hello["owner"]) <= 64
            ):
                raise ValueError("Browser worker protocol denied")
            tunnel = Tunnel(websocket, hello["owner"])
            self.tunnels[node] = tunnel
            await tunnel.send({"kind": "ready", "owner": tunnel.owner})
            while True:
                raw = await websocket.receive_text()
                if len(raw.encode()) > MAX_WIRE:
                    raise ValueError("Browser transport bound exceeded")
                value = json.loads(raw)
                queue = tunnel.channels.get(value.get("id"))
                if queue is not None:
                    # Slow consumers disconnect rather than accumulating data.
                    queue.put_nowait(value)
        except Exception:
            with contextlib.suppress(Exception):
                await websocket.close(1011)
        finally:
            if tunnel is not None:
                await tunnel.shutdown()
                if self.tunnels.get(node) is tunnel:
                    self.tunnels.pop(node)

    async def run_tunnel(self):
        base = worker_tunnel_url(self.config["executor_url"], self.fixture_loopback)
        node = self.config["node_id"]
        while not self.closing:
            try:
                async with connect(base + "/api/native-workers/" + quote(node, safe="") + "/browser-control", additional_headers={"Authorization": "Bearer " + self.host.secret}, max_size=MAX_WIRE, max_queue=8, open_timeout=10) as websocket:
                    tunnel = Tunnel(websocket, self.host.owner)
                    await tunnel.send({"protocol": PROTOCOL, "worker_version": WORKER_VERSION, "mount_id": self.host.mount_id, "owner": self.host.owner})
                    ready = json.loads(await websocket.recv())
                    if ready != {"kind": "ready", "owner": self.host.owner}:
                        raise ValueError("Browser tunnel readiness denied")
                    try:
                        async for raw in websocket:
                            value = json.loads(raw)
                            kind = value.get("kind")
                            if kind == "open":
                                args = value["args"]
                                if len(self.operations) >= MAX_CHANNELS or args["id"] in self.operations:
                                    raise ValueError("Browser operation capacity exceeded")
                                queue = asyncio.Queue(maxsize=64)
                                task = asyncio.create_task(self.execute_operation(tunnel, value, queue))
                                self.operations[args["id"]] = (task, queue)
                                task.add_done_callback(lambda done, key=args["id"]: self.operations.pop(key, None))
                            elif kind in {"input", "close"}:
                                operation = self.operations.get(value.get("id"))
                                if operation is not None:
                                    if kind == "close":
                                        operation[0].cancel()
                                    else:
                                        event = value["event"]
                                        if event.get("bytes") is not None or len((event.get("text") or "").encode()) > MAX_INPUT:
                                            raise ValueError("Browser input bound exceeded")
                                        operation[1].put_nowait(event)
                            else:
                                raise ValueError("Browser tunnel operation denied")
                    finally:
                        tasks = [task for task, _ in self.operations.values()]
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        self.operations.clear()
            except asyncio.CancelledError:
                raise
            except Exception:
                # No credential/URL/browser-state logs; no operations replay.
                await asyncio.sleep(1)

    async def execute_operation(self, tunnel, message, queue):
        args = message["args"]
        request_id = args["id"]
        try:
            scope = verify_browser_operation(message["operation"], args, message["capability"], secret=self.host.secret, node=self.config["node_id"], owner=self.host.owner)
            current = await self._current_scope(scope.thread_id, scope.user_id)
            if scope != current:
                raise ValueError("Browser thread incarnation changed")
            self.operation_scopes[request_id] = scope
            self._remember_scope(scope)
            route = "/api/threads/" + quote(scope.thread_id, safe="") + "/browser/" + ("navigate" if message["operation"] == "navigate" else "stream")
            asgi = {
                "type": "http" if message["operation"] == "navigate" else "websocket",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "scheme": args["scheme"] if message["operation"] == "navigate" else ("wss" if args["scheme"] == "https" else "ws"),
                "path": route,
                "raw_path": route.encode(),
                "query_string": args["query"].encode("ascii"),
                "root_path": "",
                "headers": [(key.encode("latin1"), value.encode("latin1")) for key, value in args["headers"]],
                "client": ("127.0.0.1", 0),
                "server": ("native-browser", 0),
                "subprotocols": [],
                "state": {},
            }
            if message["operation"] == "navigate":
                asgi["method"] = "POST"
            with browser_session_scope(scope):
                if message["operation"] == "navigate":
                    body = json.dumps({"url": args["url"]}).encode()
                    sent = False
                    response = bytearray()
                    status = 500

                    async def receive():
                        nonlocal sent
                        if not sent:
                            sent = True
                            return {"type": "http.request", "body": body, "more_body": False}
                        await asyncio.Future()

                    async def send(event):
                        nonlocal status
                        if event["type"] == "http.response.start":
                            status = event["status"]
                        elif event["type"] == "http.response.body":
                            response.extend(event.get("body", b""))
                            if len(response) > MAX_INPUT:
                                raise ValueError("Browser HTTP response bound exceeded")

                    async with asyncio.timeout(60):
                        await self.app(asgi, receive, send)
                    await tunnel.send({"kind": "http", "id": request_id, "status": status, "body": json.loads(response)})
                else:
                    connected = False

                    async def receive():
                        nonlocal connected
                        if not connected:
                            connected = True
                            return {"type": "websocket.connect"}
                        return await queue.get()

                    async def send(event):
                        await tunnel.send({"kind": "event", "id": request_id, "event": _encode_event(event)})

                    async with asyncio.timeout(300):
                        await self.app(asgi, receive, send)
        except asyncio.CancelledError:
            await self._unknown_terminal(tunnel, message["operation"], request_id)
            raise
        except Exception:
            await self._unknown_terminal(tunnel, message["operation"], request_id)
        finally:
            self.operation_scopes.pop(request_id, None)
            self._prune_scopes()

    async def _unknown_terminal(self, tunnel, operation, request_id):
        # Cancellation cannot silently strand HTTP until the full relay timeout.
        # Never replay an operation whose physical outcome is unknown.
        with contextlib.suppress(Exception):
            async with asyncio.timeout(2):
                if operation == "navigate":
                    await tunnel.send({"kind": "http", "id": request_id, "status": 503, "body": {"detail": "Browser operation outcome unknown"}})
                else:
                    await tunnel.send({"kind": "event", "id": request_id, "event": {"type": "websocket.close", "code": 1011}})

    def _prune_scopes(self):
        retained = get_browser_session_manager().retained_session_keys()
        active = {scope.key for scope in self.operation_scopes.values()} | set(self.execution_scopes)
        self.scopes = {key: scope for key, scope in self.scopes.items() if key in retained or key in active}

    def _remember_scope(self, scope):
        self._prune_scopes()
        # One physical browser, one native execution, and bounded transport ops.
        if scope.key not in self.scopes and len(self.scopes) >= MAX_CHANNELS + 2:
            raise HTTPException(503, "Browser scope registry capacity exceeded")
        self.scopes[scope.key] = scope

    async def _retire_scope(self, scope):
        tasks = [operation[0] for key, operation in list(self.operations.items()) if self.operation_scopes.get(key) == scope]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await get_browser_session_manager().close_scoped_session(scope)
        self._prune_scopes()

    async def watch_sessions(self):
        while not self.closing:
            await asyncio.sleep(1)
            for key, scope in list(self.scopes.items()):
                try:
                    current = await self._current_scope(scope.thread_id, scope.user_id)
                except Exception:
                    current = None
                if current != scope:
                    # Every operation rechecks canonical identity; retire retained
                    # pages when deletion/reset occurs even without another UI call.
                    try:
                        await self._retire_scope(scope)
                    except Exception:
                        pass  # Retain unknown physical identity/capacity.
            self._prune_scopes()

    async def stop(self):
        self.closing = True
        for task in (self.task, self.watcher):
            if task is not None:
                task.cancel()
        await asyncio.gather(*(task for task in (self.task, self.watcher) if task is not None), return_exceptions=True)
        await get_browser_session_manager().close_all_sessions()


def build_browser_control_provider(*, native_config, settings):
    return NativeBrowserControl(native_config, settings)
