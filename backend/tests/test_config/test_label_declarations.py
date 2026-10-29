"""Offline checks of the triage workflow's literal label declarations."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("label_declarations", REPO_ROOT / "scripts/check_label_declarations.py")
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


APPLIED = {
    "area:frontend",
    "area:backend",
    "area:agents",
    "area:sandbox",
    "area:skills",
    "area:mcp",
    "area:ci",
    "area:docs",
    "area:deps",
    "size/XS",
    "size/S",
    "size/M",
    "size/L",
    "size/XL",
    "risk:low",
    "risk:medium",
    "risk:high",
    "needs-validation",
    "first-time-contributor",
    "reviewing",
    "needs-triage",
}


def workflow(script: str) -> str:
    return "jobs:\n  triage:\n    steps:\n      - uses: actions/github-script@v8\n        with:\n          script: |\n" + "\n".join("            " + line for line in script.splitlines()) + "\n"


@pytest.fixture
def files(tmp_path, monkeypatch):
    labels = tmp_path / "labels.yml"
    triage = tmp_path / "triage.yml"
    labels.write_text("labels:\n" + "".join(f'  - name: "label-{i}"\n' for i in range(20)), encoding="utf-8")
    triage.write_text(workflow("github.rest.issues.addLabels({labels: ['label-0']});"), encoding="utf-8")
    monkeypatch.setattr(checker, "LABELS_FILE", labels)
    monkeypatch.setattr(checker, "TRIAGE_WORKFLOW", triage)
    return labels, triage


def test_repository_labels_are_declared():
    assert checker.applied_labels(checker.TRIAGE_WORKFLOW) == APPLIED
    assert checker.main() == 0


def test_missing_declaration_is_named(files, capsys):
    labels, triage = files
    labels.write_text("labels:\n" + "".join(f'  - name: "label-{i}"\n' for i in range(1, 21)), encoding="utf-8")
    assert checker.main() == 1
    assert "  - label-0\n" in capsys.readouterr().err


@pytest.mark.parametrize("count", [0, 19])
def test_declaration_parse_floor(files, count):
    labels, _ = files
    labels.write_text("labels:\n" + "".join(f'  - name: "label-{i}"\n' for i in range(count)), encoding="utf-8")
    with pytest.raises(SystemExit, match=f"Only {count} labels parsed"):
        checker.main()


def test_empty_extraction_fails(files):
    _, triage = files
    triage.write_text(workflow("core.info('no label operations');"), encoding="utf-8")
    with pytest.raises(SystemExit, match="No label literals"):
        checker.main()


@pytest.mark.parametrize("label", ["area:infra", "area:i18n", "awaiting-review", "priority:P1", "urgent", "needs approval", "待审核"])
def test_all_literal_label_names_are_checked(files, capsys, label):
    _, triage = files
    triage.write_text(workflow(f"github.rest.issues.addLabels({{labels: ['label-0', '{label}']}});"), encoding="utf-8")
    assert checker.main() == 1
    assert f"  - {label}\n" in capsys.readouterr().err


@pytest.mark.parametrize("comment", ["// someday maybe add 'needs-changes' here", "/* someday maybe add 'needs-changes' here */", "// addLabels({labels: ['needs-changes']});"])
def test_javascript_comments_are_not_labels(files, comment):
    _, triage = files
    triage.write_text(workflow(f"github.rest.issues.addLabels({{labels: ['label-0']}}); {comment}"), encoding="utf-8")
    assert checker.main() == 0


def test_yaml_comments_are_not_labels(files):
    _, triage = files
    triage.write_text("# someday maybe add 'needs-changes' here\n" + workflow("addLabels({labels: ['label-0']});"), encoding="utf-8")
    assert checker.main() == 0


def test_unrelated_strings_and_logs_are_not_labels(files):
    _, triage = files
    triage.write_text(workflow("const unrelated = 'needs-changes';\ncore.info('needs-changes');\ncore.info(`mentions 'needs-changes'`);\naddLabels({labels: ['label-0']});"), encoding="utf-8")
    assert checker.main() == 0


def test_tracks_arrays_aliases_ternaries_and_mutations(files, capsys):
    _, triage = files
    triage.write_text(
        workflow("""
const paths = ['docs/'];
const RULES = [['area:i18n', [/^frontend\\//]], ['area:infra', [/^docker\\//]]];
const areaLabels = RULES.filter(([, rules]) => rules.length).map(([label]) => label);
const sizeLabel = paths.includes('not-a-label') ? 'size/XS' : 'size/M';
const desired = new Set([...areaLabels, sizeLabel]);
if (paths.length) desired.add('awaiting-review');
const toAdd = [...desired].filter(n => n !== 'not-a-label');
toAdd.push('needs approval');
const alias = toAdd;
github.rest.issues.addLabels({labels: alias});
"""),
        encoding="utf-8",
    )
    assert checker.applied_labels(triage) == {"area:i18n", "area:infra", "size/XS", "size/M", "awaiting-review", "needs approval"}
    assert checker.main() == 1
    assert "not-a-label" not in capsys.readouterr().err


def test_jobs_do_not_share_variable_bindings(files):
    _, triage = files
    triage.write_text(workflow("const labels = ['label-0'];\naddLabels({labels});") + workflow("const labels = ['label-1'];\naddLabels({labels});").replace("jobs:\n", "", 1).replace("  triage:\n", "  second:\n", 1), encoding="utf-8")
    assert checker.applied_labels(triage) == {"label-0", "label-1"}


def test_escaped_quotes_and_comment_markers_in_labels(files):
    _, triage = files
    triage.write_text(workflow(r"""addLabels({labels: ["owner's // note", 'needs \'review\'', 'area:\u0069' + '18n']});"""), encoding="utf-8")
    with pytest.raises((ValueError, SystemExit), match="computed|extract"):
        checker.applied_labels(triage)


def test_escaped_label_literals(files):
    _, triage = files
    triage.write_text(workflow(r"""addLabels({"labels": ["owner's // note", 'needs \'review\'', 'area:\u006918n']});"""), encoding="utf-8")
    assert checker.applied_labels(triage) == {"owner's // note", "needs 'review'", "area:i18n"}


@pytest.mark.parametrize("script", ["addLabels({labels: computed()});", "addLabels({labels: [`label-${number}`]});"])
def test_unresolved_or_computed_values_fail_closed(files, script):
    _, triage = files
    triage.write_text(workflow(script), encoding="utf-8")
    with pytest.raises(SystemExit, match="extract|computed"):
        checker.main()


@pytest.mark.parametrize("missing", [0, 1])
def test_missing_inputs_fail(files, missing):
    files[missing].unlink()
    with pytest.raises(SystemExit, match="Missing"):
        checker.main()


@pytest.mark.parametrize(
    "script",
    [
        "const labels = ['label-0', ...unknownLabels]; addLabels({labels});",
        "const labels = ['label-0', otherLabel]; addLabels({labels});",
        "const labels = ['label-0']; const alias = labels.map(n => transform(n)); addLabels({labels: alias});",
    ],
)
def test_partial_extraction_cannot_hide_unresolved_labels(files, script):
    _, triage = files
    triage.write_text(workflow(script), encoding="utf-8")
    with pytest.raises(SystemExit, match="extract|computed"):
        checker.main()


def test_nested_conditional_labels(files):
    _, triage = files
    triage.write_text(workflow("const label = first ? second ? 'label-0' : 'label-1' : 'label-2'; addLabels({labels: [label]});"), encoding="utf-8")
    assert checker.applied_labels(triage) == {"label-0", "label-1", "label-2"}


@pytest.mark.parametrize("label", sorted(APPLIED))
def test_every_real_applied_label_is_enforced(files, capsys, label):
    labels, triage = files
    manifest = (REPO_ROOT / ".github/labels.yml").read_text(encoding="utf-8")
    labels.write_text("\n".join(line for line in manifest.splitlines() if line.strip() not in {f'- name: "{label}"', f"- name: {label}"}), encoding="utf-8")
    triage.write_text((REPO_ROOT / ".github/workflows/triage.yml").read_text(encoding="utf-8"), encoding="utf-8")
    assert checker.main() == 1
    assert f"  - {label}\n" in capsys.readouterr().err
