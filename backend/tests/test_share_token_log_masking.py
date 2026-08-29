"""Share bearer tokens must never reach any log sink (#4548).

The token is the sole credential for a public snapshot and it rides in the
URL (``/share/dfs_…`` page, ``GET /api/shares/dfs_…``). These tests pin both
redaction layers: the process-wide ``logging`` filter (uvicorn access lines
included) and the nginx access-log masking in the shipped configs.
"""

from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from deerflow.logging_config import JsonTraceFormatter, ShareTokenRedactionFilter, install_share_token_redaction

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIGS = (
    REPO_ROOT / "docker/nginx/nginx.conf",
    REPO_ROOT / "docker/nginx/nginx.local.conf",
)

_TOKEN = "dfs_A9z-_0123456789abcdefghijklmnopqrstuv"


@pytest.fixture()
def _restore_filters():
    loggers = [logging.getLogger(name) for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi")]
    saved = [
        (
            target,
            target.handlers[:],
            [h.filters[:] for h in target.handlers],
            target.filters[:],
            target.level,
            target.propagate,
            target.disabled,
        )
        for target in loggers
    ]
    yield
    for target, handlers, handler_filters, logger_filters, level, propagate, disabled in saved:
        target.handlers = handlers
        for handler, filters in zip(handlers, handler_filters, strict=True):
            handler.filters = filters
        target.filters = logger_filters
        target.level = level
        target.propagate = propagate
        target.disabled = disabled


def _record(msg, args=None):
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, msg, args, None)


def test_filter_masks_token_in_access_log_line():
    record = _record('%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", f"/api/shares/{_TOKEN}", "1.1", 200))
    assert ShareTokenRedactionFilter().filter(record) is True
    rendered = record.getMessage()
    assert _TOKEN not in rendered
    assert f"GET /api/shares/{_TOKEN}" not in rendered
    assert "/api/shares/dfs_*** HTTP/1.1" in rendered


def test_filter_preserves_real_uvicorn_access_formatter_contract():
    """AccessFormatter unpacks the original five-value args tuple."""
    from uvicorn.logging import AccessFormatter

    record = _record('%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", f"/api/shares/{_TOKEN}", "1.1", 200))
    assert ShareTokenRedactionFilter().filter(record) is True

    rendered = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s').format(record)

    assert _TOKEN not in rendered
    assert "GET /api/shares/dfs_*** HTTP/1.1" in rendered


def test_filter_masks_token_in_plain_message():
    record = _record(f"resolved share {_TOKEN} for thread-1")
    assert ShareTokenRedactionFilter().filter(record) is True
    assert record.getMessage() == "resolved share dfs_*** for thread-1"


def test_filter_masks_structured_trace_id_field():
    record = _record("ordinary message")
    record.trace_id = _TOKEN

    assert ShareTokenRedactionFilter().filter(record) is True

    assert record.trace_id == "dfs_***"


def test_filter_masks_token_in_standard_text_exception_traceback():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ShareTokenRedactionFilter())
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger = logging.Logger("deerflow.share-redaction-test", level=logging.ERROR)
    logger.addHandler(handler)

    try:
        raise RuntimeError(f"upstream URL /api/shares/{_TOKEN}")
    except RuntimeError:
        logger.exception("request failed")

    rendered = stream.getvalue()
    assert _TOKEN not in rendered
    assert "RuntimeError: upstream URL /api/shares/dfs_***" in rendered


def test_filter_masks_token_in_json_exception_traceback():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ShareTokenRedactionFilter())
    handler.setFormatter(JsonTraceFormatter())
    logger = logging.Logger("deerflow.share-redaction-test", level=logging.ERROR)
    logger.addHandler(handler)

    try:
        raise RuntimeError(f"upstream URL /api/shares/{_TOKEN}")
    except RuntimeError:
        logger.exception("request failed")

    rendered = stream.getvalue()
    payload = json.loads(rendered)
    assert _TOKEN not in rendered
    assert payload["message"] == "request failed"
    assert "RuntimeError: upstream URL /api/shares/dfs_***" in payload["exc_info"]


def test_filter_leaves_ordinary_records_untouched():
    record = _record("%s %s", ("GET", "/api/threads/thread-1/runs/wait"))
    assert ShareTokenRedactionFilter().filter(record) is True
    assert record.msg == "%s %s"
    assert record.args == ("GET", "/api/threads/thread-1/runs/wait")
    assert record.getMessage() == "GET /api/threads/thread-1/runs/wait"


def test_filter_ignores_dfs_inside_larger_words():
    # Only token-position `dfs_` is masked (left boundary): mid-word
    # occurrences keep their text, while `dfs_` after a separator still
    # masks even short bodies — fragments of truncated tokens are masked too.
    record = _record("wrote backup_dfs_2024.txt")
    assert ShareTokenRedactionFilter().filter(record) is True
    assert record.getMessage() == "wrote backup_dfs_2024.txt"

    record = _record("prefix dfs_9 suffix")
    assert ShareTokenRedactionFilter().filter(record) is True
    assert record.getMessage() == "prefix dfs_*** suffix"


@pytest.mark.parametrize("token", [f"dfs_{'A' * 43}", f"%64%66%73%5F{'A' * 43}"])
def test_filter_masks_full_token_even_when_prefixed_by_word_character(token: str):
    """A usable token remains a bearer credential when it starts at offset 1."""
    record = _record(f"trace=x{token}")

    assert ShareTokenRedactionFilter().filter(record) is True

    assert token not in record.getMessage()
    assert record.getMessage() == "trace=xdfs_***"


def test_filter_survives_malformed_format_args():
    record = _record("%d arguments but %s", ("not-a-number",))
    assert ShareTokenRedactionFilter().filter(record) is True  # not our problem to crash on


def test_install_share_token_redaction_covers_root_handlers_and_access_logger(_restore_filters):
    install_share_token_redaction()
    install_share_token_redaction()  # idempotent

    for handler in logging.getLogger().handlers:
        assert any(isinstance(f, ShareTokenRedactionFilter) for f in handler.filters)
    # The uvicorn logger tree terminates at `uvicorn`'s own handlers with
    # propagate=False, so no uvicorn record ever reaches root handlers:
    # every logger in that tree needs exactly one filter of its own — a
    # duplicate logger-level filter would double-render records.
    for name in ("uvicorn.access", "uvicorn", "uvicorn.error"):
        filters = [f for f in logging.getLogger(name).filters if isinstance(f, ShareTokenRedactionFilter)]
        assert len(filters) == 1, name


def test_install_masks_descendant_records_on_uvicorn_handlers(_restore_filters):
    """Logger filters do not run for descendant records; handler filters must."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers = [handler]
    uvicorn_logger.setLevel(logging.WARNING)
    uvicorn_logger.propagate = False

    asgi_logger = logging.getLogger("uvicorn.asgi")
    asgi_logger.handlers = []
    asgi_logger.setLevel(logging.NOTSET)
    asgi_logger.propagate = True

    install_share_token_redaction()
    asgi_logger.warning("scope path=/api/shares/%s", _TOKEN)

    rendered = stream.getvalue()
    assert _TOKEN not in rendered
    assert "scope path=/api/shares/dfs_***" in rendered


# ── nginx access-log masking ───────────────────────────────────────────────


def _map_block(config_text: str, source: str, target: str) -> str:
    declaration = f"map {source} ${target} {{"
    start = config_text.find(declaration)
    assert start >= 0, f"missing {declaration}"
    body_start = start + len(declaration)
    depth = 1
    for index in range(body_start, len(config_text)):
        if config_text[index] == "{":
            depth += 1
        elif config_text[index] == "}":
            depth -= 1
            if depth == 0:
                return config_text[body_start:index]
    raise AssertionError(f"unterminated {declaration}")


def _map_rules(config_text: str, source: str, target: str) -> tuple[str, list[tuple[str, str]]]:
    default: str | None = None
    rules: list[tuple[str, str]] = []
    line_re = re.compile(
        r'^\s*(?:"(?P<qkey>[^"]*)"|(?P<key>\S+))\s+'
        r'(?:"(?P<qvalue>[^"]*)"|(?P<value>\S+));\s*$'
    )
    for line in _map_block(config_text, source, target).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = line_re.match(line)
        assert match, f"could not parse nginx map line: {line}"
        key = match.group("qkey") if match.group("qkey") is not None else match.group("key")
        value = match.group("qvalue") if match.group("qvalue") is not None else match.group("value")
        assert key is not None and value is not None
        if key == "default":
            default = value
        else:
            rules.append((key, value))
    assert default is not None, f"${target} map has no default"
    return default, rules


def _expand_nginx_vars(value: str, variables: dict[str, str]) -> str:
    return re.sub(r"\$(\w+)", lambda match: variables[match.group(1)], value)


def _apply_nginx_map(
    config_text: str,
    source: str,
    target: str,
    input_value: str,
    variables: dict[str, str],
) -> str:
    default, rules = _map_rules(config_text, source, target)
    for key, value in rules:
        if key.startswith("~*"):
            matched = re.search(key[2:], input_value, re.IGNORECASE)
        elif key.startswith("~"):
            matched = re.search(key[1:], input_value)
        else:
            matched = input_value.lower() == key.lower()
        if matched:
            return _expand_nginx_vars(value, variables)
    return _expand_nginx_vars(default, variables)


def _mask_request_from_conf(config: Path, request_line: str) -> str:
    """Evaluate the shipped three-map masking contract for one request line."""
    config_text = config.read_text(encoding="utf-8")
    method, target, protocol = request_line.split(" ", 2)
    variables = {
        "request": request_line,
        "request_method": method,
        "server_protocol": protocol,
    }
    normalized_uri = unquote(urlsplit(target).path)
    share_log_path = _apply_nginx_map(config_text, "$uri", "share_log_path", normalized_uri, variables)
    request_has_token = _apply_nginx_map(config_text, "$request", "request_has_share_token", request_line, variables)
    variables.update(share_log_path=share_log_path, request_has_share_token=request_has_token)
    composite = f"{share_log_path}:{request_has_token}"
    return _apply_nginx_map(
        config_text,
        '"$share_log_path:$request_has_share_token"',
        "masked_request",
        composite,
        variables,
    )


def _render_masked_access_log(
    config: Path,
    *,
    request_line: str,
    referer: str,
    user_agent: str = "test-agent",
    remote_user: str = "-",
) -> str:
    config_text = config.read_text(encoding="utf-8")
    masked_request = _mask_request_from_conf(config, request_line)
    masked_referer = _apply_nginx_map(
        config_text,
        "$http_referer",
        "masked_referer",
        referer,
        {"http_referer": referer},
    )
    masked_user_agent = user_agent
    if "map $http_user_agent $masked_user_agent {" in config_text:
        masked_user_agent = _apply_nginx_map(
            config_text,
            "$http_user_agent",
            "masked_user_agent",
            user_agent,
            {"http_user_agent": user_agent},
        )
    masked_remote_user = remote_user
    if "map $remote_user $masked_remote_user {" in config_text:
        masked_remote_user = _apply_nginx_map(
            config_text,
            "$remote_user",
            "masked_remote_user",
            remote_user,
            {"remote_user": remote_user},
        )

    format_match = re.search(r"log_format\s+masked_access\s+'(?P<format>[^']+)';", config_text)
    assert format_match, f"{config.name}: missing masked_access log format"
    variables = {
        "remote_addr": "127.0.0.1",
        "remote_user": remote_user,
        "masked_remote_user": masked_remote_user,
        "time_local": "30/Aug/2026:12:00:00 +0800",
        "masked_request": masked_request,
        "status": "200",
        "body_bytes_sent": "123",
        "http_referer": referer,
        "masked_referer": masked_referer,
        "http_user_agent": user_agent,
        "masked_user_agent": masked_user_agent,
    }
    return re.sub(r"\$(\w+)", lambda match: variables[match.group(1)], format_match.group("format"))


@pytest.mark.parametrize("config_path", NGINX_CONFIGS, ids=lambda path: path.name)
def test_nginx_access_log_uses_masked_format(config_path: Path) -> None:
    config = config_path.read_text(encoding="utf-8")
    assert re.search(r"access_log\s+\S+\s+masked_access;", config), f"{config.name}: access_log must use the masked format"


@pytest.mark.parametrize("config_path", NGINX_CONFIGS, ids=lambda path: path.name)
def test_nginx_masks_share_tokens_in_access_log(config_path: Path) -> None:
    masked = _mask_request_from_conf(config_path, f"GET /share/{_TOKEN} HTTP/1.1")
    assert masked == "GET /share/*** HTTP/1.1"

    masked = _mask_request_from_conf(config_path, f"GET /api/shares/{_TOKEN} HTTP/1.1")
    assert masked == "GET /api/shares/*** HTTP/1.1"

    # Query strings ride in the same path token and are masked with it.
    masked = _mask_request_from_conf(config_path, f"GET /share/{_TOKEN}?tab=1 HTTP/1.1")
    assert masked == "GET /share/*** HTTP/1.1"

    # Management routes carry no secret in the URL and stay readable.
    for untouched in ("POST /api/threads/thread-1/shares HTTP/1.1", "GET /api/threads/thread-1/runs/wait HTTP/1.1"):
        assert _mask_request_from_conf(config_path, untouched) == untouched


@pytest.mark.parametrize("config_path", NGINX_CONFIGS, ids=lambda path: path.name)
def test_nginx_masks_share_token_in_non_share_query(config_path: Path) -> None:
    raw_request = f"GET /redirect?next=/share/{_TOKEN} HTTP/1.1"

    assert _mask_request_from_conf(config_path, raw_request) == "GET *** HTTP/1.1"


@pytest.mark.parametrize("config_path", NGINX_CONFIGS, ids=lambda path: path.name)
@pytest.mark.parametrize("encoded_route", ["/sh%61re/", "/api/sh%61res/"])
def test_nginx_masks_percent_encoded_share_routes(config_path: Path, encoded_route: str) -> None:
    """Nginx routes on normalized URI while `$request` keeps raw encoding."""
    raw_request = f"GET {encoded_route}{_TOKEN} HTTP/1.1"

    masked = _mask_request_from_conf(config_path, raw_request)

    assert _TOKEN not in masked
    assert masked.endswith("*** HTTP/1.1")


@pytest.mark.parametrize("config_path", NGINX_CONFIGS, ids=lambda path: path.name)
def test_nginx_complete_access_log_masks_share_token_referer(config_path: Path) -> None:
    rendered = _render_masked_access_log(
        config_path,
        request_line="GET /favicon.ico HTTP/1.1",
        referer=f"https://deerflow.example/share/{_TOKEN}?tab=1",
    )

    assert rendered == ('127.0.0.1 - - [30/Aug/2026:12:00:00 +0800] "GET /favicon.ico HTTP/1.1" 200 123 "dfs_***" "test-agent"')


@pytest.mark.parametrize("config_path", NGINX_CONFIGS, ids=lambda path: path.name)
def test_nginx_masks_percent_encoded_share_token_in_referer(config_path: Path) -> None:
    encoded_token = _TOKEN.replace("f", "%66", 1)
    referer = f"https://deerflow.example/share/{encoded_token}?tab=1"

    rendered = _render_masked_access_log(
        config_path,
        request_line="GET /favicon.ico HTTP/1.1",
        referer=referer,
    )

    assert encoded_token not in rendered
    assert '"dfs_***" "test-agent"' in rendered


@pytest.mark.parametrize("config_path", NGINX_CONFIGS, ids=lambda path: path.name)
def test_nginx_masks_share_token_in_user_agent_and_remote_user(config_path: Path) -> None:
    rendered = _render_masked_access_log(
        config_path,
        request_line="GET /favicon.ico HTTP/1.1",
        referer="-",
        user_agent=f"client/{_TOKEN}",
        remote_user=_TOKEN,
    )

    assert _TOKEN not in rendered
    assert rendered.count("dfs_***") == 2


def _location_block(config_text: str, location: str) -> str:
    """Extract one `location ^~ <path> { … }` block from an nginx config."""
    start = config_text.index(f"location ^~ {location} {{")
    depth = 0
    for index in range(start, len(config_text)):
        if config_text[index] == "{":
            depth += 1
        elif config_text[index] == "}":
            depth -= 1
            if depth == 0:
                return config_text[start:index]
    raise AssertionError(f"unterminated location block for {location}")


@pytest.mark.parametrize("config_path", NGINX_CONFIGS, ids=lambda path: path.name)
@pytest.mark.parametrize("location", ["/api/shares/", "/share/"])
def test_nginx_share_locations_suppress_request_lines_in_error_log(config_path: Path, location: str) -> None:
    """nginx error messages embed the full request line, severity does not
    redact it (nginx trac #2193 documents crit-level failures that still
    append the request line), and error_log cannot be format-masked — so the
    share locations must route error_log to a non-retaining sink."""
    block = _location_block(config_path.read_text(encoding="utf-8"), location)
    # Severity alone does not redact request lines (nginx trac #2193): the
    # sink itself must be non-retaining, and it must be the ONLY error_log
    # directive in the block — nginx honors multiple error_log directives,
    # so a second, retaining directive would reintroduce the leak.
    directives = re.findall(r"error_log\s+([^;]+);", block)
    assert directives == ["/dev/null crit"], f"{config_path.name} {location}: expected exactly one error_log to /dev/null crit, got {directives}"
