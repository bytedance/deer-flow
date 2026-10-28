"""Keep retrieved paper metadata intact across long tool outputs and delegation."""

import importlib.util
import io
import json
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from xml.sax.saxutils import escape

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/public/systematic-literature-review/scripts"


@pytest.fixture
def evidence_merger():
    spec = importlib.util.spec_from_file_location("slr_merge_extractions", SCRIPTS / "merge_extractions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def paper_record(paper_id="2601.00001"):
    return {
        "id": paper_id,
        "title": "Retrieved title",
        "authors": ["Original Author"],
        "published": "2026-01-01",
        "categories": ["cs.AI"],
        "abs_url": f"https://arxiv.org/abs/{paper_id}",
        "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
    }


def extraction(paper_id="2601.00001"):
    return {
        "arxiv_id": paper_id,
        "research_question": "Which evidence is available?",
        "methodology": "Abstract-only assessment.",
        "key_findings": ["Finding from the abstract."],
        "limitations": "Full text was not reviewed.",
    }


def test_merge_restores_canonical_metadata_and_retrieval_order(evidence_merger):
    papers = [paper_record("2601.00001"), paper_record("2601.00002")]

    merged = evidence_merger.merge(papers, [[extraction("2601.00002")], [extraction("2601.00001")]])

    assert [item["arxiv_id"] for item in merged] == [paper["id"] for paper in papers]
    for item in merged:
        assert item["title"] == "Retrieved title"
        assert item["authors"] == ["Original Author"]
        assert item["published_date"] == "2026-01-01"
        assert item["methodology"] == "Abstract-only assessment."
        assert item["categories"] == ["cs.AI"]
        assert item["abs_url"] == f"https://arxiv.org/abs/{item['arxiv_id']}"


@pytest.mark.parametrize(
    "invalid",
    [
        {"title": ""},
        {"title": None},
        {"authors": []},
        {"authors": "Original Author"},
        {"authors": [""]},
        {"published": "not a date"},
    ],
)
def test_merge_rejects_incomplete_source_metadata(evidence_merger, invalid):
    with pytest.raises(ValueError):
        evidence_merger.merge([{**paper_record(), **invalid}], [[extraction()]])


@pytest.mark.parametrize(
    "batches",
    [
        [[extraction("9999.99999")]],
        [[extraction(), extraction()]],
        [[]],
        [[{**extraction(), "title": "Invented title"}]],
        [[{**extraction(), "authors": ["Invented Author"]}]],
        [[{**extraction(), "published_date": "1999-01-01"}]],
        [[{**extraction(), "categories": ["invented.category"]}]],
        [[{**extraction(), "abs_url": "https://example.com/invented"}]],
        [[{**extraction(), "key_findings": "not an array"}]],
        [[{**extraction(), "limitations": None}]],
        [["not a paper object"]],
        [{"not": "an extraction array"}],
    ],
)
def test_merge_rejects_untrusted_or_incomplete_worker_results(evidence_merger, batches):
    with pytest.raises(ValueError):
        evidence_merger.merge([paper_record()], batches)


@pytest.mark.parametrize(
    "invalid",
    [
        [],
        [""],
        [" \t\n"],
        ["Finding from the abstract.", ""],
        ["Finding from the abstract.", " \t\n"],
        ["Finding from the abstract.", None],
    ],
)
def test_merge_rejects_empty_or_invalid_findings(evidence_merger, invalid):
    with pytest.raises(ValueError, match="2601.00001: invalid or missing key_findings"):
        evidence_merger.merge([paper_record()], [[{**extraction(), "key_findings": invalid}]])


@pytest.mark.parametrize("field", ["research_question", "methodology", "limitations"])
@pytest.mark.parametrize("invalid", ["", " \t\n"])
def test_merge_rejects_blank_analysis_text(evidence_merger, field, invalid):
    with pytest.raises(ValueError, match=f"2601.00001: invalid or missing {field}"):
        evidence_merger.merge([paper_record()], [[{**extraction(), field: invalid}]])


def test_merge_preserves_nonblank_analysis_without_trimming(evidence_merger):
    analysis = {
        "research_question": "  Which evidence is available?\n",
        "methodology": "\tAbstract-only assessment. ",
        "key_findings": ["  First finding.\n", "\tSecond finding. "],
        "limitations": "\nFull text was not reviewed. ",
    }

    merged = evidence_merger.merge([paper_record()], [[{**extraction(), **analysis}]])

    assert {field: merged[0][field] for field in analysis} == analysis


def test_merge_cli_rejects_unknown_ids_without_creating_output(evidence_merger, monkeypatch, tmp_path, capsys):
    papers_path, results_path, output_path = (tmp_path / name for name in ("papers.json", "result.json", "merged.json"))
    papers_path.write_text(json.dumps([paper_record()]), encoding="utf-8")
    results_path.write_text(json.dumps([extraction("9999.99999")]), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "merge_extractions.py",
            "--papers",
            str(papers_path),
            "--extractions",
            str(results_path),
            "--output",
            str(output_path),
        ],
    )

    assert evidence_merger.main() == 1
    assert not output_path.exists()
    assert "9999.99999" in capsys.readouterr().err


def test_merge_cli_reads_bom_and_does_not_overwrite_output(evidence_merger, monkeypatch, tmp_path, capsys):
    papers_path, results_path, output_path = (tmp_path / name for name in ("papers.json", "result.json", "merged.json"))
    papers_path.write_text(json.dumps([paper_record()]), encoding="utf-8-sig")
    results_path.write_text(json.dumps([extraction()]), encoding="utf-8-sig")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "merge_extractions.py",
            "--papers",
            str(papers_path),
            "--extractions",
            str(results_path),
            "--output",
            str(output_path),
        ],
    )

    assert evidence_merger.main() == 0
    original = output_path.read_bytes()
    assert not original.startswith(b"\xef\xbb\xbf")
    assert json.loads(original)[0]["title"] == "Retrieved title"
    assert evidence_merger.main() == 1
    assert output_path.read_bytes() == original
    assert capsys.readouterr().err


@pytest.fixture
def arxiv_client(monkeypatch):
    spec = importlib.util.spec_from_file_location("slr_arxiv_search", SCRIPTS / "arxiv_search.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    get = Mock()
    monkeypatch.setattr(module.requests, "get", get)
    return module, get


def atom_feed(count):
    entries = []
    for index in range(count):
        entries.append(
            f"""<entry><id>http://arxiv.org/abs/2601.{index:05}v2</id>
            <title>{escape(f"论文 {index} & evidence")}</title>
            <author><name>Author {index}</name></author>
            <published>2026-01-01T00:00:00Z</published>
            <summary>{"Long abstract. " * 200}</summary>
            <category term="cs.AI" /></entry>"""
        )
    return '<feed xmlns="http://www.w3.org/2005/Atom">' + "".join(entries) + "</feed>"


def test_file_mode_preserves_long_results_and_only_prints_artifact_paths(arxiv_client, monkeypatch, tmp_path, capsys):
    module, get = arxiv_client
    get.return_value = SimpleNamespace(text=atom_feed(12), raise_for_status=lambda: None)
    destination = tmp_path / "evidence"
    monkeypatch.setattr(sys, "argv", ["arxiv_search.py", "agent memory", "--output-dir", str(destination)])

    assert module.main() == 0

    stdout = capsys.readouterr().out
    manifest = json.loads(stdout)
    assert len(stdout) < 12000
    assert "Long abstract" not in stdout
    assert manifest["paper_count"] == 12
    papers = json.loads(Path(manifest["papers_path"]).read_text(encoding="utf-8"))
    assert len(json.dumps(papers)) > 12000
    assert papers[0]["title"] == "论文 0 & evidence"
    assert papers[0]["id"] == "2601.00000"
    delegated = []
    sizes = []
    for batch_path in manifest["batch_paths"]:
        paths = json.loads(Path(batch_path).read_text(encoding="utf-8"))
        sizes.append(len(paths))
        delegated.extend(json.loads(Path(path).read_text(encoding="utf-8")) for path in paths)
    assert sizes == [5, 5, 2]
    assert delegated == papers
    get.assert_called_once()


def test_stdout_mode_still_returns_the_original_json_array(arxiv_client, monkeypatch, capsys):
    module, get = arxiv_client
    get.return_value = SimpleNamespace(text=atom_feed(1), raise_for_status=lambda: None)
    monkeypatch.setattr(sys, "argv", ["arxiv_search.py", "agent memory"])

    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "2601.00000"


def test_empty_search_has_no_delegation_batches(arxiv_client, monkeypatch, tmp_path, capsys):
    module, get = arxiv_client
    get.return_value = SimpleNamespace(text=atom_feed(0), raise_for_status=lambda: None)
    monkeypatch.setattr(sys, "argv", ["arxiv_search.py", "absent", "--output-dir", str(tmp_path / "empty")])

    assert module.main() == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["paper_count"] == 0
    assert manifest["batch_paths"] == []
    assert json.loads(Path(manifest["papers_path"]).read_text(encoding="utf-8")) == []


def test_existing_evidence_is_not_overwritten(arxiv_client, monkeypatch, tmp_path, capsys):
    module, get = arxiv_client
    get.return_value = SimpleNamespace(text=atom_feed(1), raise_for_status=lambda: None)
    marker = tmp_path / "papers.json"
    marker.write_text("original evidence", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["arxiv_search.py", "topic", "--output-dir", str(tmp_path)])

    assert module.main() == 1
    assert marker.read_text(encoding="utf-8") == "original evidence"
    assert capsys.readouterr().err


def test_failed_retrieval_does_not_publish_an_evidence_manifest(arxiv_client, monkeypatch, tmp_path, capsys):
    module, get = arxiv_client
    get.side_effect = OSError("offline")
    destination = tmp_path / "evidence"
    monkeypatch.setattr(sys, "argv", ["arxiv_search.py", "topic", "--output-dir", str(destination)])

    assert module.main() == 1
    assert not destination.exists()
    output = capsys.readouterr()
    assert output.out == ""
    assert "offline" in output.err


def test_file_mode_works_with_the_stdlib_http_fallback(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "requests", None)
    spec = importlib.util.spec_from_file_location("slr_arxiv_fallback", SCRIPTS / "arxiv_search.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    response = io.BytesIO(atom_feed(1).encode())
    response.status = 200
    urlopen = Mock(return_value=response)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sys, "argv", ["arxiv_search.py", "agent memory", "--output-dir", str(tmp_path / "evidence")])

    assert module.main() == 0

    manifest = json.loads(capsys.readouterr().out)
    assert json.loads(Path(manifest["papers_path"]).read_text(encoding="utf-8"))[0]["id"] == "2601.00000"
    assert "agent+memory" in urlopen.call_args.args[0].full_url


@pytest.fixture
def report_publisher(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("slr_publish_report", SCRIPTS / "publish_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "report",
    [
        "No references were included.",
        "https://arxiv.org/abs/9999.99999",
        "https://arxiv.org/abs/2601.00001 plus arXiv:9999.99999",
        "https://arxiv.org/abs/2601.00001 plus https://arxiv.org/abs/hep-th/9901001",
        "https://arxiv.org/abs/2601.00001 plus https://arxiv.org/abs/not-a-paper",
        "https://arxiv.org/abs/2601.00001 plus https://arxiv.org/abs/9999%2E99999",
    ],
)
def test_publish_refuses_missing_or_unretrieved_report_ids(report_publisher, report, tmp_path):
    output = tmp_path / "published.md"
    with pytest.raises(ValueError):
        report_publisher.publish([paper_record()], [[extraction()]], report, output)
    assert not output.exists()


def test_publish_checks_original_evidence_again_and_keeps_existing_output(report_publisher, tmp_path):
    output = tmp_path / "published.md"
    report = "Retrieved title: https://arxiv.org/abs/2601.00001v2\n"
    with pytest.raises(ValueError):
        report_publisher.publish([paper_record()], [[{**extraction(), "title": "Invented"}]], report, output)
    assert not output.exists()
    report_publisher.publish([paper_record()], [[extraction()]], report, output)
    assert output.read_text(encoding="utf-8") == report
    with pytest.raises(FileExistsError):
        report_publisher.publish([paper_record()], [[extraction()]], report + "changed", output)
    assert output.read_text(encoding="utf-8") == report


@pytest.mark.parametrize("paper_id", ["2601.00001", "hep-th/9901001", "math.GT/0301001"])
def test_publish_supports_modern_and_legacy_ids(report_publisher, paper_id, tmp_path):
    report = f"https://arxiv.org/abs/{paper_id}v2\n"
    report_publisher.publish([paper_record(paper_id)], [[extraction(paper_id)]], report, tmp_path / "report.md")


def test_publish_cli_reads_bom_and_returns_no_success_path_on_failure(report_publisher, tmp_path, monkeypatch, capsys):
    papers, analyses, draft, output = (tmp_path / name for name in ("papers.json", "analyses.json", "draft.md", "report.md"))
    papers.write_text(json.dumps([paper_record()]), encoding="utf-8-sig")
    analyses.write_text(json.dumps([extraction()]), encoding="utf-8-sig")
    draft.write_text("https://arxiv.org/abs/9999.99999", encoding="utf-8-sig")
    monkeypatch.setattr(sys, "argv", ["publish_report.py", "--papers", str(papers), "--extractions", str(analyses), "--draft", str(draft), "--output", str(output)])
    assert report_publisher.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "9999.99999" in captured.err
    assert not output.exists()
    draft.write_text("https://arxiv.org/abs/2601.00001\n", encoding="utf-8-sig")
    assert report_publisher.main() == 0
    assert json.loads(capsys.readouterr().out)["output_path"] == str(output.resolve())
    assert not output.read_bytes().startswith(b"\xef\xbb\xbf")
