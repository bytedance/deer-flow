"""Keep pull requests out of repository issue research, across both transports."""

import io
import json
import runpy
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


@pytest.fixture(params=["requests", "urllib"])
def issue_client(request, monkeypatch):
    if request.param == "urllib":
        monkeypatch.setitem(sys.modules, "requests", None)
    script = (
        Path(__file__).resolve().parents[2]
        / "skills/public/github-deep-research/scripts/github_api.py"
    )
    module = runpy.run_path(str(script))
    pages = []
    calls = []

    if request.param == "urllib":

        def fake_urlopen(prepared, timeout):
            calls.append(prepared.full_url)
            payload, status = pages.pop(0)
            data = json.dumps(payload).encode()
            if status >= 400:
                raise urllib.error.HTTPError(prepared.full_url, status, "error", {}, io.BytesIO(data))
            response = io.BytesIO(data)
            response.status = status
            return response

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    else:
        requests = pytest.importorskip("requests")

        def fake_send(session, prepared, **kwargs):
            calls.append(prepared.url)
            payload, status = pages.pop(0)
            response = requests.Response()
            response.status_code = status
            response._content = json.dumps(payload).encode()
            return response

        monkeypatch.setattr(requests.Session, "send", fake_send)

    return module["GitHubAPI"](), pages, calls


def test_issue_limit_counts_issues_instead_of_pull_requests(issue_client):
    client, pages, calls = issue_client
    pages.extend([
        ([{"number": 10, "pull_request": {}}, {"number": 9}], 200),
        ([{"number": 8, "pull_request": {}}, {"number": 7}], 200),
    ])

    assert client.get_issues("owner", "repo", state="open", limit=2, labels="bug,help wanted") == [{"number": 9}, {"number": 7}]
    assert len(calls) == 2
    for index, url in enumerate(calls):
        assert urlsplit(url).path == "/repos/owner/repo/issues"
        parameters = parse_qs(urlsplit(url).query)
        assert parameters["state"] == ["open"]
        assert parameters["labels"] == ["bug,help wanted"]
        assert parameters["per_page"] == ["2"]
        assert parameters.get("page", ["1"]) == [str(index + 1)]


def test_issue_search_continues_after_a_page_of_only_pull_requests(issue_client):
    client, pages, calls = issue_client
    pages.extend([
        ([{"number": 5, "pull_request": {}}, {"number": 4, "pull_request": {}}], 200),
        ([{"number": 3}], 200),
    ])

    assert client.get_issues("owner", "repo", limit=2) == [{"number": 3}]
    assert len(calls) == 2


def test_issue_search_stops_at_an_empty_page(issue_client):
    client, pages, calls = issue_client
    pages.extend([([{"number": 2, "pull_request": {}}], 200), ([], 200)])

    assert client.get_issues("owner", "repo", limit=1) == []
    assert len(calls) == 2


def test_issue_search_does_not_fetch_an_unneeded_page(issue_client):
    client, pages, calls = issue_client
    pages.append(([{"number": 2}, {"number": 1}], 200))

    assert client.get_issues("owner", "repo", limit=2) == [{"number": 2}, {"number": 1}]
    assert len(calls) == 1


def test_last_page_does_not_exceed_the_requested_issue_limit(issue_client):
    client, pages, calls = issue_client
    pages.extend([
        ([{"number": 4}, {"number": 3, "pull_request": {}}], 200),
        ([{"number": 2}, {"number": 1}], 200),
    ])

    assert client.get_issues("owner", "repo", limit=2) == [{"number": 4}, {"number": 2}]
    assert len(calls) == 2


@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_issue_limit_does_not_make_a_request(issue_client, limit):
    client, pages, calls = issue_client
    pages.append(([], 200))

    assert client.get_issues("owner", "repo", limit=limit) == []
    assert calls == []


def test_later_page_failure_is_not_returned_as_partial_research(issue_client):
    client, pages, calls = issue_client
    pages.extend([([{"number": 3}, {"number": 2, "pull_request": {}}], 200), ({"message": "rate limited"}, 403)])

    with pytest.raises(Exception, match="403"):
        client.get_issues("owner", "repo", limit=2)
    assert len(calls) == 2
