"""Project-document uploads through nginx must not be capped at nginx's 1m default.

``POST /api/projects/{project_id}/documents`` is a multipart upload that Gateway
accepts up to ``uploads.max_file_size`` (50 MiB by default, the same limit as
thread uploads). No nginx location matched it, so it fell through to the
``/api/`` catch-all, which carries no ``client_max_body_size``: nginx answered
a 2 MB PDF with a bare 413 before Gateway ever saw the request. Reproduced on
``nginx:alpine`` with the shipped config -- the same body sent to
``/api/threads/{id}/uploads`` passed nginx's size check.

The route needs its own location, with the uploads route's settings, in all
three maintained configs.
"""

from __future__ import annotations

import re

import pytest
from support.nginx_conf import NGINX_CONFIGS, extract_location_block, parse_body_size_bytes, parse_read_timeout_seconds, read_config

from app.gateway.routers.project_documents import router as project_documents_router
from app.gateway.routers.uploads import DEFAULT_MAX_FILE_SIZE

PROJECT_DOCUMENTS_LOCATION = r"~ ^/api/projects/[^/]+/documents"
UPLOADS_LOCATION = r"~ ^/api/threads/[^/]+/uploads"

# The /api/ catch-all these routes used to land on grants blocking Gateway calls
# this much; moving them to their own location must not take it away.
_MIN_READ_TIMEOUT_SECONDS = 600


def _location_regex(selector: str) -> re.Pattern[str]:
    """The PCRE nginx evaluates for a ``~`` location, as a Python pattern (identical for these anchors and classes)."""
    assert selector.startswith("~ ")
    return re.compile(selector[2:])


def _router_paths() -> list[str]:
    """Concrete request paths for every route the project-documents router serves."""
    paths = []
    for route in project_documents_router.routes:
        path = route.path.replace("{project_id}", "proj-42").replace("{document_id}", "doc-7").replace("{thread_id}", "thread-9")
        paths.append(path)
    assert paths, "project-documents router has no routes"
    return paths


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_project_documents_route_allows_the_upload_limit_gateway_enforces(path):
    """The location must admit at least what Gateway accepts, and stream it."""
    block = extract_location_block(read_config(path), PROJECT_DOCUMENTS_LOCATION)

    size_bytes = parse_body_size_bytes(block)
    uploads_size_bytes = parse_body_size_bytes(extract_location_block(read_config(path), UPLOADS_LOCATION))

    assert size_bytes >= DEFAULT_MAX_FILE_SIZE, f"{path}: project documents client_max_body_size is {size_bytes} bytes but Gateway accepts {DEFAULT_MAX_FILE_SIZE} by default; nginx would 413 a file Gateway allows"
    assert size_bytes == uploads_size_bytes, f"{path}: project documents and thread uploads share uploads.max_file_size, so their nginx ceilings must match"
    assert "proxy_request_buffering off;" in block, f"{path}: uploads must stream to Gateway instead of spooling to client_body_temp"


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_project_documents_route_keeps_the_catchall_read_timeout(path):
    """attach-to-thread copies into a sandbox and content downloads stream; both used to get /api/'s 600s."""
    block = extract_location_block(read_config(path), PROJECT_DOCUMENTS_LOCATION)
    catchall = extract_location_block(read_config(path), "/api/")

    assert parse_read_timeout_seconds(block) >= max(_MIN_READ_TIMEOUT_SECONDS, parse_read_timeout_seconds(catchall))


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_project_documents_location_matches_every_router_path_and_nothing_else(path):
    """The regex must cover the whole router (the upload is one of five routes) without swallowing the project routes above it."""
    content = read_config(path)
    extract_location_block(content, PROJECT_DOCUMENTS_LOCATION)  # the selector under test is really in this file
    pattern = _location_regex(PROJECT_DOCUMENTS_LOCATION)

    for request_path in _router_paths():
        assert pattern.search(request_path), f"{path}: {request_path} would fall through to /api/ and its 1m default"
    for other in ("/api/projects", "/api/projects/proj-42", "/api/projects/proj-42/threads", "/api/projectsx/documents", "/api/threads/t/uploads"):
        assert not pattern.search(other), f"{path}: {other} must not be routed as a project document"


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_project_documents_location_proxies_like_its_neighbours(path):
    """Same upstream and forwarded headers as the uploads route, so only the size policy differs from /api/."""
    content = read_config(path)
    block = extract_location_block(content, PROJECT_DOCUMENTS_LOCATION)
    uploads = extract_location_block(content, UPLOADS_LOCATION)

    def directives(text: str) -> set[str]:
        return {line.strip() for line in text.splitlines() if re.match(r"\s*(proxy_pass|proxy_http_version|proxy_set_header)\b", line)}

    assert directives(block) == directives(uploads)


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_api_catchall_still_keeps_nginx_default_body_policy(path):
    """The fix is a dedicated location, not a blanket raise on /api/ (auth, config writes and JSON routes stay at the default)."""
    block = extract_location_block(read_config(path), "/api/")

    assert "client_max_body_size" not in block
    assert "proxy_request_buffering" not in block
