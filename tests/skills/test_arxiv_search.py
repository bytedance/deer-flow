"""Exercise arXiv Atom parsing through both offline HTTP transports."""

import importlib.util
import io
import sys
import urllib.request
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/systematic-literature-review/scripts/arxiv_search.py"
)


def feed(identifier=None, title="A paper", summary="An abstract"):
    entry = ""
    if identifier is not None:
        entry = f"""<entry>
            <id>{identifier}</id><title>{title}</title><summary>{summary}</summary>
            <published>2017-06-12T17:57:34Z</published>
            <updated>2017-06-13T17:57:34Z</updated>
            <author><name>A Researcher</name></author>
            <category term="cs.CL" />
            <link title="pdf" href="https://arxiv.org/pdf/1706.03762v5" />
        </entry>"""
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{entry}</feed>'


@pytest.fixture(params=["requests", "urllib"])
def client(request, monkeypatch):
    if request.param == "urllib":
        monkeypatch.setitem(sys.modules, "requests", None)
    else:
        requests = pytest.importorskip("requests")
    spec = importlib.util.spec_from_file_location("arxiv_search_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    response = {"xml": feed(), "status": 200}

    if request.param == "urllib":

        def fake_urlopen(req, timeout):
            stream = io.BytesIO(response["xml"].encode("utf-8"))
            stream.status = response["status"]
            return stream

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    else:

        def fake_send(self, prepared, **kwargs):
            result = requests.Response()
            result.status_code = response["status"]
            result._content = response["xml"].encode("utf-8")
            result.encoding = "utf-8"
            return result

        monkeypatch.setattr(requests.Session, "send", fake_send)
    return module, response


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("fragment", ["", "#invalid_query"])
def test_search_rejects_atom_error_entries(client, scheme, fragment):
    module, response = client
    response["xml"] = feed(
        f"{scheme}://arxiv.org/api/errors{fragment}",
        title="Error",
        summary="unsupported sortBy value",
    )

    with pytest.raises(ValueError, match="arXiv API error: unsupported sortBy value"):
        module.search("transformer attention")


def test_cli_reports_atom_error_without_paper_json(client, monkeypatch, capsys):
    module, response = client
    response["xml"] = feed(
        "http://arxiv.org/api/errors#invalid_query",
        title="Error",
        summary="unsupported sortBy value",
    )
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "transformer attention"])

    assert module.main() == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "arXiv API error: unsupported sortBy value" in output.err


@pytest.mark.parametrize("title", ["A paper", "Error"])
def test_search_preserves_real_papers_including_error_titles(client, title):
    module, response = client
    response["xml"] = feed("https://arxiv.org/abs/1706.03762v5", title=title)

    assert module.search("transformer attention") == [
        {
            "id": "1706.03762",
            "title": title,
            "authors": ["A Researcher"],
            "abstract": "An abstract",
            "published": "2017-06-12",
            "updated": "2017-06-13",
            "categories": ["cs.CL"],
            "pdf_url": "https://arxiv.org/pdf/1706.03762v5",
            "abs_url": "https://arxiv.org/abs/1706.03762v5",
        }
    ]


def test_search_preserves_empty_results(client):
    module, response = client
    response["xml"] = feed()

    assert module.search("no matching papers") == []


def test_search_still_checks_http_errors_before_xml(client):
    module, response = client
    response.update(status=503, xml="not XML")

    with pytest.raises(Exception, match="503"):
        module.search("transformer attention")
