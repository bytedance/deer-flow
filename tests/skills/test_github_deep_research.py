"""Exercise the GitHub research client's dependency-free HTTP fallback."""

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
