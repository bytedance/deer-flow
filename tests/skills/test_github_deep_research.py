"""Exercise the GitHub research client's HTTP transports without network IO."""

import http.client
import io
import runpy
import sys
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


@pytest.fixture
def fallback_client(monkeypatch):
    monkeypatch.setitem(sys.modules, "requests", None)
    script = (
        Path(__file__).resolve().parents[2]
        / "skills/public/github-deep-research/scripts/github_api.py"
    )
    module = runpy.run_path(str(script))
    captured = {}

    def fake_urlopen(request, timeout):
        # Validate the request target as the real HTTP transport does, without IO.
        connection = http.client.HTTPSConnection("api.github.com")
        try:
            connection.putrequest("GET", request.selector)
        finally:
            connection.close()
        captured.update(url=request.full_url, timeout=timeout, headers=request.headers)
        response = io.BytesIO(b'{"ok": true}')
        response.status = 200
        return response

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return module["GitHubAPI"](), captured


@pytest.fixture(params=["requests", "urllib"])
def file_content_client(request, monkeypatch):
    if request.param == "urllib":
        return request.getfixturevalue("fallback_client")

    requests = pytest.importorskip("requests")
    script = (
        Path(__file__).resolve().parents[2]
        / "skills/public/github-deep-research/scripts/github_api.py"
    )
    module = runpy.run_path(str(script))
    captured = {}

    def fake_send(session, prepared_request, **kwargs):
        captured["url"] = prepared_request.url
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"ok": true}'
        return response

    monkeypatch.setattr(requests.Session, "send", fake_send)
    return module["GitHubAPI"](), captured


@pytest.mark.parametrize(
    ("path", "encoded_path"),
    [
        ("docs/C# guide.md", "docs/C%23%20guide.md"),
        ("docs/query?draft.md", "docs/query%3Fdraft.md"),
        ("docs/literal%20name.md", "docs/literal%2520name.md"),
        ("文档/入门 guide.md", "%E6%96%87%E6%A1%A3/%E5%85%A5%E9%97%A8%20guide.md"),
        ("docs/file name.md", "docs/file%20name.md"),
        ("src/nested/README.md", "src/nested/README.md"),
    ],
)
def test_file_content_preserves_repository_path(
    file_content_client, path, encoded_path
):
    client, captured = file_content_client

    assert client.get_file_content("owner", "repo", path) == '{"ok": true}'

    url = urlsplit(captured["url"])
    assert url.path == f"/repos/owner/repo/contents/{encoded_path}"
    assert url.query == ""
    assert url.fragment == ""


@pytest.mark.parametrize("query", ["bug fix", "C++ & retry#fragment", "模型请求"])
def test_fallback_search_preserves_query(fallback_client, query):
    client, captured = fallback_client

    assert client.search_issues("owner", "repo", query) == {"ok": True}

    url = urlsplit(captured["url"])
    assert url.path == "/search/issues"
    assert url.fragment == ""
    assert parse_qs(url.query) == {
        "q": [f"repo:owner/repo {query}"],
        "per_page": ["30"],
    }


def test_fallback_issues_preserves_filters(fallback_client):
    client, captured = fallback_client

    assert client.get_issues(
        "owner", "repo", state="open", limit=10, labels="bug,help wanted"
    ) == {"ok": True}

    assert parse_qs(urlsplit(captured["url"]).query) == {
        "state": ["open"],
        "per_page": ["10"],
        "labels": ["bug,help wanted"],
    }


def test_fallback_ordinary_parameters(fallback_client):
    client, captured = fallback_client

    assert client.get_contributors("owner", "repo", limit=10) == {"ok": True}

    assert parse_qs(urlsplit(captured["url"]).query) == {"per_page": ["10"]}
    assert captured["timeout"] == 30
    assert captured["headers"]["User-agent"] == "Deep-Research-Bot/1.0"


def test_fallback_without_parameters(fallback_client):
    client, captured = fallback_client

    assert client.get_repo_info("owner", "repo") == {"ok": True}

    assert captured["url"] == "https://api.github.com/repos/owner/repo"
