"""Share bearer tokens must never reach any log sink (#4548).

The token is the sole credential for a public snapshot and it rides in the
URL (``/share/dfs_…`` page, ``GET /api/shares/dfs_…``). These tests pin both
redaction layers: the process-wide ``logging`` filter (uvicorn access lines
included) and the nginx access-log masking in the shipped configs.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from deerflow.logging_config import ShareTokenRedactionFilter, install_share_token_redaction

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIGS = (
    REPO_ROOT / "docker/nginx/nginx.conf",
    REPO_ROOT / "docker/nginx/nginx.local.conf",
)

_TOKEN = "dfs_A9z-_0123456789abcdefghijklmnopqrstuv"


@pytest.fixture()
def _restore_filters():
    loggers = [logging.getLogger(name) for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error")]
    saved = [(target, target.handlers[:], [h.filters[:] for h in target.handlers], target.filters[:]) for target in loggers]
    yield
    for target, handlers, handler_filters, logger_filters in saved:
        target.handlers = handlers
        for handler, filters in zip(handlers, handler_filters, strict=True):
            handler.filters = filters
        target.filters = logger_filters


def _record(msg, args=None):
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, msg, args, None)


def test_filter_masks_token_in_access_log_line():
    record = _record('%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", f"/api/shares/{_TOKEN}", "1.1", 200))
    assert ShareTokenRedactionFilter().filter(record) is True
    rendered = record.getMessage()
    assert _TOKEN not in rendered
    assert f"GET /api/shares/{_TOKEN}" not in rendered
    assert "/api/shares/dfs_*** HTTP/1.1" in rendered


def test_filter_masks_token_in_plain_message():
    record = _record(f"resolved share {_TOKEN} for thread-1")
    assert ShareTokenRedactionFilter().filter(record) is True
    assert record.getMessage() == "resolved share dfs_*** for thread-1"


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


# ── nginx access-log masking ───────────────────────────────────────────────


def _masked_request_from_conf(config: Path) -> tuple[re.Pattern[str], str]:
    """Extract the masking ``map $request`` entry from an nginx config."""
    config_text = config.read_text(encoding="utf-8")
    map_block = re.search(r"map \$request \$masked_request \{(.*?)\}", config_text, re.DOTALL)
    assert map_block, f"{config.name}: missing $request masking map"
    entry = re.search(r'"(?P<regex>~[^"]+)"\s+(?P<value>\S+)', map_block.group(1))
    assert entry, f"{config.name}: masking map has no regex entry"
    # nginx PCRE named groups use (?<name>…); Python needs (?P<name>…).
    regex = entry.group("regex").replace("(?<", "(?P<")
    regex = re.sub(r"^~\*?", "", regex)  # strip the ~ / ~* case flag
    value = entry.group("value").rstrip(";")
    return re.compile(regex, re.IGNORECASE), value


def _apply(pattern: re.Pattern[str], value: str, request_line: str) -> str:
    match = pattern.match(request_line)
    if not match:
        return request_line  # nginx map default keeps the original line
    return re.sub(r"\$(\w+)", lambda m: match.group(m.group(1)), value)


@pytest.mark.parametrize("config_path", NGINX_CONFIGS, ids=lambda path: path.name)
def test_nginx_access_log_uses_masked_format(config_path: Path) -> None:
    config = config_path.read_text(encoding="utf-8")
    assert re.search(r"access_log\s+\S+\s+masked_access;", config), f"{config.name}: access_log must use the masked format"


@pytest.mark.parametrize("config_path", NGINX_CONFIGS, ids=lambda path: path.name)
def test_nginx_masks_share_tokens_in_access_log(config_path: Path) -> None:
    pattern, value = _masked_request_from_conf(config_path)

    masked = _apply(pattern, value, f"GET /share/{_TOKEN} HTTP/1.1")
    assert masked == "GET /share/*** HTTP/1.1"

    masked = _apply(pattern, value, f"GET /api/shares/{_TOKEN} HTTP/1.1")
    assert masked == "GET /api/shares/*** HTTP/1.1"

    # Query strings ride in the same path token and are masked with it.
    masked = _apply(pattern, value, f"GET /share/{_TOKEN}?tab=1 HTTP/1.1")
    assert masked == "GET /share/*** HTTP/1.1"

    # Management routes carry no secret in the URL and stay readable.
    for untouched in ("POST /api/threads/thread-1/shares HTTP/1.1", "GET /api/threads/thread-1/runs/wait HTTP/1.1"):
        assert _apply(pattern, value, untouched) == untouched


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
    # sink itself must be non-retaining.
    assert re.search(r"error_log\s+/dev/null\s+crit;", block), f"{config_path.name} {location}: error_log must route to /dev/null"
