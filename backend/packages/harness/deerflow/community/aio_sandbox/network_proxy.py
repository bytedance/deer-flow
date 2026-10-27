"""Trusted HTTP(S) policy proxy used by restricted local AIO sandboxes.

The module is copied into a small sidecar container and executed as a script.
It deliberately supports only HTTP absolute-form requests and HTTPS CONNECT;
all other protocols remain unavailable on the sandbox's internal-only network.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hmac
import ipaddress
import json
import os
import socket
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

MAX_HEADER_BYTES = 65_536
POLICY_DB = Path(os.environ.get("DEERFLOW_POLICY_DB", "/tmp/deerflow-network-policy.sqlite3"))
RELAY_AUTH_HEADER = "X-DeerFlow-Relay-Token"
RELAY_TOKEN_ENV = "DEERFLOW_RELAY_TOKEN"


class _InvalidHttpRequest(ValueError):
    pass


class _InvalidHttpBody(_InvalidHttpRequest):
    pass


class _InvalidHttpHeader(_InvalidHttpRequest):
    pass


_HTTP_TOKEN_CHARS = frozenset("!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _connect_db() -> sqlite3.Connection:
    db = sqlite3.connect(POLICY_DB, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            request_id TEXT PRIMARY KEY,
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            method TEXT NOT NULL,
            created_at REAL NOT NULL,
            surfaced INTEGER NOT NULL DEFAULT 0,
            decision TEXT
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS grants (
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            expires_at REAL,
            PRIMARY KEY (host, port)
        )
        """
    )
    db.commit()
    return db


def normalize_host(raw: str) -> str | None:
    host = raw.strip().lower().rstrip(".")
    if not host or len(host) > 253 or any(char in host for char in "/\\\x00\r\n"):
        return None
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def domain_matches(host: str, rule: str) -> bool:
    if rule.startswith("*."):
        suffix = rule[2:]
        return host.endswith("." + suffix) and host != suffix
    return host == rule


def address_is_public(address: str, *, allow_synthetic_dns: bool = False) -> bool:
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if parsed.is_global and not parsed.is_multicast and not getattr(parsed, "is_site_local", False):
        return True
    # Docker Desktop's DNS inhibition layer maps public names into the
    # benchmarking-only 198.18.0.0/15 range. Accept it only when the host
    # backend explicitly identifies Desktop; native Linux keeps rejecting it.
    return allow_synthetic_dns and parsed in ipaddress.ip_network("198.18.0.0/15")


def _static_rules() -> tuple[str, ...]:
    try:
        raw = json.loads(os.environ.get("DEERFLOW_ALLOW_DOMAINS_JSON", "[]"))
    except json.JSONDecodeError:
        return ()
    return tuple(value for value in raw if isinstance(value, str))


def _policy_mode() -> str:
    value = os.environ.get("DEERFLOW_NETWORK_MODE", "isolated")
    return value if value in {"isolated", "allowlist"} else "isolated"


def _is_granted(host: str, port: int, now: float) -> bool:
    with _connect_db() as db:
        row = db.execute("SELECT expires_at FROM grants WHERE host = ? AND port = ?", (host, port)).fetchone()
        if row is None:
            return False
        expires_at = row[0]
        if expires_at is not None and float(expires_at) <= now:
            db.execute("DELETE FROM grants WHERE host = ? AND port = ?", (host, port))
            return False
        return True


def policy_allows(host: str, port: int, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if _policy_mode() != "allowlist":
        return False
    if any(domain_matches(host, rule) for rule in _static_rules()):
        return True
    return _is_granted(host, port, now)


def record_denial(host: str, port: int, method: str) -> str:
    now = time.time()
    with _connect_db() as db:
        # Serialize the read-before-insert deduplication so simultaneous proxy
        # requests cannot create multiple approval cards for one destination.
        db.execute("BEGIN IMMEDIATE")
        recent = db.execute(
            "SELECT request_id FROM events WHERE host = ? AND port = ? AND decision IS NULL AND created_at >= ? ORDER BY created_at DESC LIMIT 1",
            (host, port, now - 30),
        ).fetchone()
        if recent is not None:
            return str(recent[0])
        request_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO events(request_id, host, port, method, created_at) VALUES (?, ?, ?, ?, ?)",
            (request_id, host, port, method, now),
        )
        return request_id


def pending_events() -> list[dict[str, object]]:
    with _connect_db() as db:
        # Tool execution timestamps cannot reliably delimit proxy events: a
        # background process may emit a denial after its launching tool returns,
        # and subagent/non-interactive paths must drain events without prompting.
        # Claim the oldest unsurfaced event atomically, independent of age.
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT request_id, host, port, method, created_at FROM events WHERE surfaced = 0 AND decision IS NULL ORDER BY created_at LIMIT 1",
        ).fetchone()
        if row is not None:
            db.execute("UPDATE events SET surfaced = 1 WHERE request_id = ?", (row[0],))
            # One Human Input card makes one destination decision. Close any
            # sibling denials from the same tool call so a later retry records
            # a fresh event instead of leaving an invisible surfaced request.
            db.execute("UPDATE events SET decision = 'superseded' WHERE surfaced = 0 AND decision IS NULL")
    if row is None:
        return []
    return [{"request_id": row[0], "host": row[1], "port": row[2], "method": row[3], "created_at": row[4]}]


def deny_pending_events() -> int:
    """Atomically deny every event that has not been surfaced to a user."""
    with _connect_db() as db:
        db.execute("BEGIN IMMEDIATE")
        result = db.execute("UPDATE events SET surfaced = 1, decision = 'deny' WHERE surfaced = 0 AND decision IS NULL")
        return max(result.rowcount, 0)


def decide(request_id: str, decision: str, ttl: int) -> bool:
    with _connect_db() as db:
        row = db.execute("SELECT host, port, decision FROM events WHERE request_id = ?", (request_id,)).fetchone()
        if row is None:
            return False
        host, port, existing = str(row[0]), int(row[1]), row[2]
        if existing is not None:
            return str(existing) == decision
        if decision == "allow_temporary":
            db.execute(
                "INSERT INTO grants(host, port, expires_at) VALUES (?, ?, ?) ON CONFLICT(host, port) DO UPDATE SET expires_at = excluded.expires_at",
                (host, port, time.time() + ttl),
            )
        elif decision == "allow_sandbox":
            db.execute(
                "INSERT INTO grants(host, port, expires_at) VALUES (?, ?, NULL) ON CONFLICT(host, port) DO UPDATE SET expires_at = NULL",
                (host, port),
            )
        elif decision != "deny":
            return False
        db.execute("UPDATE events SET decision = ? WHERE request_id = ?", (decision, request_id))
        return True


async def resolve_public(host: str, port: int) -> tuple[tuple[int, tuple], ...] | None:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    allow_synthetic_dns = os.environ.get("DEERFLOW_ALLOW_SYNTHETIC_DNS") == "1"
    public = [(family, sockaddr) for family, _socktype, _proto, _canonname, sockaddr in infos if address_is_public(str(sockaddr[0]), allow_synthetic_dns=allow_synthetic_dns)]
    if len(public) != len(infos) or not public:
        return None
    return tuple(public)


async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65_536):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()


async def _open_public(resolved: tuple[tuple[int, tuple], ...], port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
    """Try every pre-validated DNS answer within one shared deadline."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 15
    for index, (family, sockaddr) in enumerate(resolved):
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        # Reserve an equal share of the remaining budget for every later
        # address so a black-holed first answer cannot consume the full
        # deadline and strand otherwise reachable candidates.
        attempt_timeout = remaining / (len(resolved) - index)
        try:
            return await asyncio.wait_for(
                asyncio.open_connection(sockaddr[0], port, family=family),
                timeout=attempt_timeout,
            )
        except (OSError, TimeoutError):
            continue
    return None


async def _reject(writer: asyncio.StreamWriter, status: str, body: str) -> None:
    encoded = body.encode("utf-8")
    writer.write(f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {len(encoded)}\r\nConnection: close\r\n\r\n".encode() + encoded)
    await writer.drain()
    writer.close()
    await writer.wait_closed()


def _parse_http_header_fields(header_lines: list[str]) -> list[tuple[str, str, str]]:
    """Parse one header block using a single strict field-name grammar."""
    fields: list[tuple[str, str, str]] = []
    for line in header_lines:
        if not line:
            continue
        if line.startswith((" ", "\t")) or ":" not in line:
            raise _InvalidHttpHeader("Obsolete or malformed HTTP headers are not supported")
        raw_name, raw_value = line.split(":", 1)
        if not raw_name or any(char not in _HTTP_TOKEN_CHARS for char in raw_name):
            raise _InvalidHttpHeader("HTTP field names must use token characters followed immediately by a colon")
        if any((ord(char) < 0x20 and char != "\t") or ord(char) == 0x7F for char in raw_value):
            raise _InvalidHttpHeader("HTTP field values cannot contain control characters")
        fields.append((raw_name, raw_name.lower(), raw_value.strip(" \t")))
    return fields


def _http_request_body_framing(header_fields: list[tuple[str, str, str]]) -> tuple[str, int]:
    """Return the strictly validated framing for one HTTP proxy request."""
    content_lengths = [value for _raw_name, name, value in header_fields if name == "content-length"]
    transfer_encodings = [value.lower() for _raw_name, name, value in header_fields if name == "transfer-encoding"]
    if content_lengths and transfer_encodings:
        raise _InvalidHttpBody("Content-Length and Transfer-Encoding cannot be combined")
    if transfer_encodings:
        if transfer_encodings != ["chunked"]:
            raise _InvalidHttpBody("Only a single chunked Transfer-Encoding is supported")
        return ("chunked", 0)
    if not content_lengths:
        return ("fixed", 0)
    if len(content_lengths) != 1 or not content_lengths[0].isdigit():
        raise _InvalidHttpBody("Content-Length must be one non-negative decimal integer")
    return ("fixed", int(content_lengths[0]))


def _build_http_outbound_header(method: str, path: str, version: str, header_fields: list[tuple[str, str, str]]) -> bytes:
    """Strip proxy/hop headers and force the one-request upstream connection closed."""
    connection_tokens = {token.strip().lower() for _raw_name, name, value in header_fields if name == "connection" for token in value.split(",") if token.strip()}
    if any(any(char not in _HTTP_TOKEN_CHARS for char in token) for token in connection_tokens):
        raise _InvalidHttpHeader("Connection header options must use HTTP token characters")
    if connection_tokens & {"host", "content-length", "transfer-encoding"}:
        raise _InvalidHttpBody("Connection cannot remove request framing headers")
    hop_headers = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "upgrade",
        *connection_tokens,
    }
    kept_headers = [f"{raw_name}: {value}" for raw_name, name, value in header_fields if name not in hop_headers]
    kept_headers.append("Connection: close")
    return f"{method} {path} {version}\r\n".encode("latin-1") + "\r\n".join(kept_headers).encode("latin-1") + b"\r\n\r\n"


async def _copy_exact_request_bytes(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, length: int) -> None:
    remaining = length
    while remaining:
        chunk = await asyncio.wait_for(reader.readexactly(min(remaining, 65_536)), timeout=15)
        writer.write(chunk)
        await writer.drain()
        remaining -= len(chunk)


async def _copy_chunked_request_body(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Relay exactly one strictly framed chunked body, including its trailers."""
    while True:
        line = await asyncio.wait_for(reader.readuntil(b"\r\n"), timeout=15)
        if len(line) > MAX_HEADER_BYTES:
            raise _InvalidHttpBody("Chunk header is too large")
        size_token = line[:-2].split(b";", 1)[0].strip()
        if not size_token or any(value not in b"0123456789abcdefABCDEF" for value in size_token):
            raise _InvalidHttpBody("Invalid chunk size")
        size = int(size_token, 16)
        writer.write(line)
        await writer.drain()
        if size:
            await _copy_exact_request_bytes(reader, writer, size)
            terminator = await asyncio.wait_for(reader.readexactly(2), timeout=15)
            if terminator != b"\r\n":
                raise _InvalidHttpBody("Invalid chunk terminator")
            writer.write(terminator)
            await writer.drain()
            continue

        trailer_bytes = len(line)
        while True:
            trailer = await asyncio.wait_for(reader.readuntil(b"\r\n"), timeout=15)
            trailer_bytes += len(trailer)
            if trailer_bytes > MAX_HEADER_BYTES:
                raise _InvalidHttpBody("Chunk trailers are too large")
            if trailer != b"\r\n" and (trailer.startswith((b" ", b"\t")) or b":" not in trailer):
                raise _InvalidHttpBody("Invalid chunk trailer")
            writer.write(trailer)
            await writer.drain()
            if trailer == b"\r\n":
                return


def _parse_authority(authority: str, default_port: int) -> tuple[str, int] | None:
    parsed = urlsplit("//" + authority)
    try:
        port = parsed.port or default_port
    except ValueError:
        return None
    host = normalize_host(parsed.hostname or "")
    if host is None:
        return None
    return host, port


async def _read_tls_client_hello(reader: asyncio.StreamReader) -> tuple[str, bytes] | None:
    """Read one TLS ClientHello and return its normalized SNI plus wire bytes."""
    wire = bytearray()
    handshake = bytearray()
    expected_handshake_size: int | None = None
    while len(wire) <= MAX_HEADER_BYTES:
        try:
            record_header = await asyncio.wait_for(reader.readexactly(5), timeout=15)
            record_size = int.from_bytes(record_header[3:5], "big")
            if record_header[0] != 22 or record_size <= 0 or len(wire) + 5 + record_size > MAX_HEADER_BYTES:
                return None
            record = await asyncio.wait_for(reader.readexactly(record_size), timeout=15)
        except (asyncio.IncompleteReadError, TimeoutError):
            return None
        wire.extend(record_header)
        wire.extend(record)
        handshake.extend(record)
        if expected_handshake_size is None and len(handshake) >= 4:
            if handshake[0] != 1:
                return None
            expected_handshake_size = 4 + int.from_bytes(handshake[1:4], "big")
            if expected_handshake_size > MAX_HEADER_BYTES:
                return None
        if expected_handshake_size is not None and len(handshake) >= expected_handshake_size:
            break
    if expected_handshake_size is None or len(handshake) < expected_handshake_size:
        return None

    hello = memoryview(handshake)[4:expected_handshake_size]
    try:
        offset = 2 + 32
        offset += 1 + hello[offset]
        cipher_size = int.from_bytes(hello[offset : offset + 2], "big")
        offset += 2 + cipher_size
        offset += 1 + hello[offset]
        extensions_size = int.from_bytes(hello[offset : offset + 2], "big")
        offset += 2
        extensions_end = offset + extensions_size
        if extensions_end > len(hello):
            return None
        sni: str | None = None
        while offset + 4 <= extensions_end:
            extension_type = int.from_bytes(hello[offset : offset + 2], "big")
            extension_size = int.from_bytes(hello[offset + 2 : offset + 4], "big")
            offset += 4
            extension = hello[offset : offset + extension_size]
            offset += extension_size
            if offset > extensions_end:
                return None
            # Reject encrypted ClientHello: its hidden SNI cannot be compared
            # with the approved CONNECT host without TLS interception.
            if extension_type in {0xFE0D, 0xFFCE}:
                return None
            if extension_type != 0 or len(extension) < 5:
                continue
            names_size = int.from_bytes(extension[0:2], "big")
            cursor = 2
            while cursor + 3 <= 2 + names_size and cursor + 3 <= len(extension):
                name_type = extension[cursor]
                name_size = int.from_bytes(extension[cursor + 1 : cursor + 3], "big")
                cursor += 3
                if cursor + name_size > len(extension):
                    return None
                if name_type == 0:
                    sni = normalize_host(bytes(extension[cursor : cursor + name_size]).decode("ascii"))
                    break
                cursor += name_size
        return (sni, bytes(wire)) if sni is not None else None
    except (IndexError, UnicodeDecodeError, ValueError):
        return None


async def handle_proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
        await _reject(writer, "400 Bad Request", "Invalid proxy request")
        return
    if len(header) > MAX_HEADER_BYTES:
        await _reject(writer, "431 Request Header Fields Too Large", "Proxy request headers are too large")
        return
    try:
        request_line, *header_lines = header.decode("latin-1").split("\r\n")
        method, target, version = request_line.split(" ", 2)
    except ValueError:
        await _reject(writer, "400 Bad Request", "Invalid proxy request line")
        return
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        await _reject(writer, "400 Bad Request", "Unsupported HTTP version")
        return
    try:
        header_fields = _parse_http_header_fields(header_lines)
    except _InvalidHttpHeader as exc:
        await _reject(writer, "400 Bad Request", str(exc))
        return

    method = method.upper()
    if method == "CONNECT":
        parsed = _parse_authority(target, 443)
        if parsed is None or parsed[1] != 443:
            await _reject(writer, "403 Forbidden", "Only HTTPS CONNECT on port 443 is supported")
            return
        host, port = parsed
        outbound_header = None
    else:
        parsed_url = urlsplit(target)
        if parsed_url.scheme.lower() != "http" or not parsed_url.hostname:
            await _reject(writer, "403 Forbidden", "Only HTTP absolute-form requests and HTTPS CONNECT are supported")
            return
        try:
            port = parsed_url.port or 80
        except ValueError:
            await _reject(writer, "400 Bad Request", "Invalid destination port")
            return
        host = normalize_host(parsed_url.hostname)
        if host is None or port != 80:
            await _reject(writer, "403 Forbidden", "Only HTTP on port 80 is supported")
            return
        path = parsed_url.path or "/"
        if parsed_url.query:
            path += "?" + parsed_url.query
        host_headers = [value for _raw_name, name, value in header_fields if name == "host"]
        host_authority = _parse_authority(host_headers[0], 80) if len(host_headers) == 1 else None
        if host_authority != (host, port):
            await _reject(writer, "400 Bad Request", "HTTP Host header must match the approved proxy destination")
            return
        if any(name == "expect" for _raw_name, name, _value in header_fields):
            await _reject(writer, "417 Expectation Failed", "Expect is not supported by the sandbox network proxy")
            return
        try:
            body_mode, body_length = _http_request_body_framing(header_fields)
            outbound_header = _build_http_outbound_header(method, path, version, header_fields)
        except _InvalidHttpRequest as exc:
            await _reject(writer, "400 Bad Request", str(exc))
            return

    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        await _reject(writer, "403 Forbidden", "IP-literal destinations are not allowed by sandbox network policy")
        return
    if not policy_allows(host, port):
        if os.environ.get("DEERFLOW_RECORD_DENIALS") == "1":
            request_id = record_denial(host, port, method)
            detail = f" (request {request_id})"
        else:
            detail = ""
        await _reject(writer, "403 Forbidden", f"Sandbox network policy denied {host}:{port}{detail}")
        return
    resolved = await resolve_public(host, port)
    if resolved is None:
        await _reject(writer, "403 Forbidden", "Destination did not resolve exclusively to public addresses")
        return
    upstream = await _open_public(resolved, port)
    if upstream is None:
        await _reject(writer, "403 Forbidden", "Destination did not resolve exclusively to public addresses")
        return
    upstream_reader, upstream_writer = upstream
    if method == "CONNECT":
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        client_hello = await _read_tls_client_hello(reader)
        if client_hello is None or client_hello[0] != host:
            upstream_writer.close()
            await upstream_writer.wait_closed()
            writer.close()
            await writer.wait_closed()
            return
        upstream_writer.write(client_hello[1])
        await upstream_writer.drain()
        await asyncio.gather(_relay(reader, upstream_writer), _relay(upstream_reader, writer))
        return

    upstream_writer.write(outbound_header or b"")
    await upstream_writer.drain()
    try:
        if body_mode == "chunked":
            await _copy_chunked_request_body(reader, upstream_writer)
        else:
            await _copy_exact_request_bytes(reader, upstream_writer, body_length)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, _InvalidHttpBody) as exc:
        upstream_writer.close()
        await upstream_writer.wait_closed()
        await _reject(writer, "400 Bad Request", str(exc) or "Invalid HTTP request body")
        return
    if upstream_writer.can_write_eof():
        upstream_writer.write_eof()
        await upstream_writer.drain()
    try:
        # One request per client connection is intentional. Relaying arbitrary
        # remaining client bytes would let a pipelined request bypass the next
        # destination/Host policy check.
        await _relay(upstream_reader, writer)
    finally:
        with contextlib.suppress(Exception):
            upstream_writer.close()
            await upstream_writer.wait_closed()


async def handle_relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
        await _reject(writer, "400 Bad Request", "Invalid sandbox relay request")
        return
    if len(header) > MAX_HEADER_BYTES:
        await _reject(writer, "431 Request Header Fields Too Large", "Sandbox relay request headers are too large")
        return
    try:
        _request_line, *header_lines = header.decode("latin-1").split("\r\n")
        header_fields = _parse_http_header_fields(header_lines)
    except (UnicodeDecodeError, _InvalidHttpHeader):
        await _reject(writer, "400 Bad Request", "Invalid sandbox relay request headers")
        return
    expected_token = os.environ.get(RELAY_TOKEN_ENV, "")
    presented_tokens = [value for _raw_name, name, value in header_fields if name == RELAY_AUTH_HEADER.lower()]
    presented_token = presented_tokens[0].encode("latin-1") if len(presented_tokens) == 1 else b""
    if not expected_token or len(presented_tokens) != 1 or not hmac.compare_digest(presented_token, expected_token.encode()):
        await _reject(writer, "403 Forbidden", "Sandbox relay authentication failed")
        return

    target = os.environ.get("DEERFLOW_SANDBOX_TARGET", "")
    parsed = _parse_authority(target, 8080)
    if parsed is None:
        await _reject(writer, "502 Bad Gateway", "Sandbox relay target is invalid")
        return
    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(asyncio.open_connection(parsed[0], parsed[1]), timeout=5)
    except (OSError, TimeoutError):
        await _reject(writer, "502 Bad Gateway", "Sandbox is not ready")
        return
    upstream_writer.write(header)
    await upstream_writer.drain()
    await asyncio.gather(_relay(reader, upstream_writer), _relay(upstream_reader, writer))


async def serve() -> None:
    _connect_db().close()
    proxy = await asyncio.start_server(handle_proxy, "0.0.0.0", 3128, limit=MAX_HEADER_BYTES)
    relay = await asyncio.start_server(handle_relay, "0.0.0.0", 8080, limit=MAX_HEADER_BYTES)
    async with proxy, relay:
        await asyncio.gather(proxy.serve_forever(), relay.serve_forever())


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve")
    subparsers.add_parser("pending")
    subparsers.add_parser("deny-pending")
    decide_parser = subparsers.add_parser("decide")
    decide_parser.add_argument("request_id")
    decide_parser.add_argument("decision", choices=("deny", "allow_temporary", "allow_sandbox"))
    decide_parser.add_argument("--ttl", type=int, default=300)
    args = parser.parse_args()
    if args.command == "serve":
        asyncio.run(serve())
        return 0
    if args.command == "pending":
        print(json.dumps(pending_events(), separators=(",", ":")))
        return 0
    if args.command == "deny-pending":
        print(deny_pending_events())
        return 0
    if args.command == "decide":
        return 0 if decide(args.request_id, args.decision, args.ttl) else 2
    parser.error("a command is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
