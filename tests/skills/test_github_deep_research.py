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
        response = io.BytesIO(captured.get("body", b'{"ok": true}'))
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
    captured["body"] = b'[{"number": 1}]'

    assert client.get_issues(
        "owner", "repo", state="open", limit=10, labels="bug,help wanted"
    ) == [{"number": 1}]

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


def test_tree_asks_for_the_repository_head(file_content_client):
    client, captured = file_content_client

    assert client.get_tree("owner", "repo") == {"ok": True}

    url = urlsplit(captured["url"])
    assert url.path == "/repos/owner/repo/git/trees/HEAD"
    assert parse_qs(url.query) == {"recursive": ["1"]}


def test_tree_keeps_an_explicit_branch(file_content_client):
    client, captured = file_content_client

    assert client.get_tree("owner", "repo", branch="dev", recursive=False) == {
        "ok": True
    }

    url = urlsplit(captured["url"])
    assert url.path == "/repos/owner/repo/git/trees/dev"
    assert url.query == ""


def test_tree_does_not_guess_another_branch(monkeypatch, fallback_client):
    client, _ = fallback_client
    asked: list[str] = []

    def fail_after_recording(endpoint, params=None, accept=None):
        asked.append(endpoint)
        raise RuntimeError("HTTP 404")

    monkeypatch.setattr(client, "_get", fail_after_recording)

    with pytest.raises(RuntimeError):
        client.get_tree("owner", "repo")

    # A stale `master` still resolves as a branch, so retrying names here silently
    # returns the stale branch's tree instead of failing.
    assert asked == ["/repos/owner/repo/git/trees/HEAD"]


def _client_returning_status(monkeypatch, transport, status, body=b'{"ok": true}'):
    """One client whose transport answers ``status`` for every request, plus its module.

    Both transports are exercised because the script picks one at import time: a fix that
    only holds for ``requests`` would leave the fallback (the path taken when the dependency is
    missing) answering an error as content.
    """
    script = (
        Path(__file__).resolve().parents[2]
        / "skills/public/github-deep-research/scripts/github_api.py"
    )
    if transport == "urllib":
        monkeypatch.setitem(sys.modules, "requests", None)
        module = runpy.run_path(str(script))

        def fake_urlopen(request, timeout):
            response = io.BytesIO(body)
            response.status = status
            return response

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        return module["GitHubAPI"](), module

    requests = pytest.importorskip("requests")
    monkeypatch.delitem(sys.modules, "requests", raising=False)
    module = runpy.run_path(str(script))

    def fake_send(session, prepared_request, **kwargs):
        response = requests.Response()
        response.status_code = status
        response._content = body
        response.url = prepared_request.url
        return response

    monkeypatch.setattr(requests.Session, "send", fake_send)
    return module["GitHubAPI"](), module


@pytest.mark.parametrize("transport", ["requests", "urllib"])
@pytest.mark.parametrize("status", [404, 403])
def test_a_failed_readme_fetch_is_an_error_not_content(monkeypatch, transport, status):
    client, module = _client_returning_status(monkeypatch, transport, status)

    with pytest.raises(module["GitHubAPIError"]) as excinfo:
        client.get_readme("owner", "repo")

    message = str(excinfo.value)
    assert "README" in message and "owner/repo" in message
    assert str(status) in message, "the HTTP status must stay visible"


def test_a_rate_limit_is_distinguishable_from_a_missing_repository(
    monkeypatch,
):
    limited, module = _client_returning_status(monkeypatch, "requests", 403)
    with pytest.raises(module["GitHubAPIError"]) as excinfo:
        limited.get_readme("owner", "repo")
    limited_message = str(excinfo.value)

    monkeypatch.undo()
    missing, module = _client_returning_status(monkeypatch, "requests", 404)
    with pytest.raises(module["GitHubAPIError"]) as excinfo:
        missing.get_readme("owner", "repo")
    missing_message = str(excinfo.value)

    assert "403" in limited_message and "404" not in limited_message
    assert "404" in missing_message and "403" not in missing_message


@pytest.mark.parametrize("transport", ["requests", "urllib"])
def test_a_failed_file_fetch_names_the_path(monkeypatch, transport):
    client, module = _client_returning_status(monkeypatch, transport, 404)

    with pytest.raises(module["GitHubAPIError"]) as excinfo:
        client.get_file_content("owner", "repo", "docs/guide.md")

    message = str(excinfo.value)
    assert "docs/guide.md" in message and "404" in message


@pytest.mark.parametrize("transport", ["requests", "urllib"])
def test_the_cli_reports_a_fetch_failure_on_stderr_and_exits_nonzero(
    monkeypatch, capsys, transport
):
    """The success channel stays empty: a caller reading stdout cannot mistake a failure for a
    README body, and the exit code says the run did not succeed."""
    _, module = _client_returning_status(monkeypatch, transport, 404)
    monkeypatch.setattr(
        sys, "argv", ["github_api.py", "owner", "repo", "readme"]
    )

    with pytest.raises(SystemExit) as excinfo:
        module["main"]()

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert captured.out == ""
    assert "404" in captured.err
