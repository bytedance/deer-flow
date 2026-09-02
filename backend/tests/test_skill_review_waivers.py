from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import review_changed_public_skills as runner
import skill_review_waivers as waiver_support
from jsonschema import Draft202012Validator, FormatChecker
from skill_review_waivers import (
    EMPTY_MANIFEST,
    SCHEMA_VERSION,
    SkillReviewWaiver,
    WaiverManifest,
    WaiverManifestError,
    matching_waiver,
    parse_manifest,
    validate_manifest_against_facts,
)

from deerflow.skills.review.analyzer import analyze_skill_package
from deerflow.skills.review.readers import LocalDirectoryReader

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_target(repo_root: Path, content: bytes = b"safe subprocess invocation\n") -> tuple[Path, str]:
    target = repo_root / "skills/public/demo/scripts/run.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target, f"sha256:{hashlib.sha256(content).hexdigest()}"


def _waiver(
    *,
    digest: str,
    expires_on: date = date(2027, 2, 28),
    preapproved_file_sha256s: tuple[str, ...] = (),
) -> SkillReviewWaiver:
    return SkillReviewWaiver(
        package="skills/public/demo",
        source="skillscan",
        rule_id="python-subprocess",
        path="scripts/run.py",
        line=12,
        evidence="subprocess.run",
        file_sha256=digest,
        reason="Fixed executable and argv invocation with shell disabled.",
        expires_on=expires_on,
        preapproved_file_sha256s=preapproved_file_sha256s,
    )


def _finding(*, severity: str = "error", line: int = 12) -> dict[str, object]:
    return {
        "source": "skillscan",
        "rule_id": "python-subprocess",
        "path": "scripts/run.py",
        "line": line,
        "evidence": "subprocess.run",
        "severity": severity,
        "message": "Subprocess usage detected.",
    }


def _payload(
    *,
    digest: str,
    path: str = "scripts/run.py",
    duplicate: bool = False,
    preapproved_file_sha256s: object | None = None,
) -> bytes:
    entry = {
        "package": "skills/public/demo",
        "source": "skillscan",
        "rule_id": "python-subprocess",
        "path": path,
        "line": 12,
        "evidence": "subprocess.run",
        "file_sha256": digest,
        "reason": "Fixed executable and argv invocation with shell disabled.",
        "expires_on": "2027-02-28",
    }
    if preapproved_file_sha256s is not None:
        entry["preapproved_file_sha256s"] = preapproved_file_sha256s
    return json.dumps({"schema_version": SCHEMA_VERSION, "waivers": [entry, entry] if duplicate else [entry]}).encode()


def test_committed_manifest_matches_schema_and_strict_parser() -> None:
    manifest_path = REPO_ROOT / ".github/skill-review-waivers.v1.json"
    schema = json.loads((REPO_ROOT / "contracts/skill_review/waiver_manifest.v1.schema.json").read_text(encoding="utf-8"))
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    parsed = parse_manifest(manifest_path.read_bytes(), source=str(manifest_path))

    assert len(parsed.waivers) == 2
    assert parsed.waivers[0].preapproved_file_sha256s == ("sha256:2877bde08bf3f437b9dae3d57585a0840b9b1024736d2e5c6c657b71899269d0",)
    assert parsed.waivers[1].preapproved_file_sha256s == ("sha256:ea2521ba41c8fd16b2900758c890bb6c6d2b4b01da10b4a860facb8587ed0bde",)


def test_skill_creator_waivers_match_current_error_findings() -> None:
    package = REPO_ROOT / "skills/public/skill-creator"
    manifest = parse_manifest((REPO_ROOT / ".github/skill-review-waivers.v1.json").read_bytes(), source="committed manifest")
    facts = analyze_skill_package(LocalDirectoryReader(package).read(), profile="deerflow")

    validation_errors = validate_manifest_against_facts(
        manifest,
        facts_by_package={"skills/public/skill-creator": facts},
        repo_root=REPO_ROOT,
        today=date(2026, 8, 31),
    )
    assert validation_errors == []


@pytest.mark.parametrize("path", ["../run.py", "/tmp/run.py", "scripts\\run.py", "scripts/../run.py"])
def test_parser_rejects_noncanonical_or_traversing_paths(tmp_path: Path, path: str) -> None:
    _, digest = _write_target(tmp_path)

    with pytest.raises(WaiverManifestError, match="canonical relative POSIX path|backslashes"):
        parse_manifest(_payload(digest=digest, path=path), source="test manifest")


def test_parser_rejects_duplicate_exact_waivers(tmp_path: Path) -> None:
    _, digest = _write_target(tmp_path)

    with pytest.raises(WaiverManifestError, match="duplicates an earlier waiver"):
        parse_manifest(_payload(digest=digest, duplicate=True), source="test manifest")


@pytest.mark.parametrize(
    ("preapproved", "error"),
    [
        ("sha256:" + "1" * 64, "must be an array"),
        (["sha256:" + "1" * 63], "64 lowercase hex characters"),
        (["sha256:" + "1" * 64] * 2, "entries must be unique"),
        (["PRIMARY"], "must not repeat file_sha256"),
        ([f"sha256:{index:064x}" for index in range(9)], "at most 8 entries"),
    ],
)
def test_parser_rejects_invalid_preapproved_hashes(tmp_path: Path, preapproved: object, error: str) -> None:
    _, digest = _write_target(tmp_path)
    value = [digest] if preapproved == ["PRIMARY"] else preapproved

    with pytest.raises(WaiverManifestError, match=error):
        parse_manifest(
            _payload(digest=digest, preapproved_file_sha256s=value),
            source="test manifest",
        )


def test_missing_manifest_at_ref_means_no_waivers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        waiver_support.subprocess,
        "run",
        lambda *args, **kwargs: waiver_support.subprocess.CompletedProcess(args[0], 128, stdout=b"", stderr=b"missing"),
    )

    manifest = waiver_support.load_manifest_at_ref(tmp_path, "a" * 40, label="trusted base")

    assert manifest is EMPTY_MANIFEST


def test_matching_waiver_requires_exact_finding_and_current_file_hash(tmp_path: Path) -> None:
    target, digest = _write_target(tmp_path)
    manifest = WaiverManifest((_waiver(digest=digest),))

    assert matching_waiver(_finding(), package="skills/public/demo", manifest=manifest, repo_root=tmp_path, today=date(2026, 8, 31)) is manifest.waivers[0]
    assert matching_waiver(_finding(line=13), package="skills/public/demo", manifest=manifest, repo_root=tmp_path, today=date(2026, 8, 31)) is None

    target.write_bytes(b"changed\n")
    assert matching_waiver(_finding(), package="skills/public/demo", manifest=manifest, repo_root=tmp_path, today=date(2026, 8, 31)) is None


def test_preapproved_file_hash_authorizes_a_later_file_revision(tmp_path: Path) -> None:
    target, current_digest = _write_target(tmp_path)
    future_content = b"safe subprocess invocation with explicit UTF-8\n"
    future_digest = f"sha256:{hashlib.sha256(future_content).hexdigest()}"
    waiver = _waiver(digest=current_digest, preapproved_file_sha256s=(future_digest,))
    manifest = WaiverManifest((waiver,))
    facts = {"findings": [_finding()]}

    assert (
        validate_manifest_against_facts(
            manifest,
            facts_by_package={waiver.package: facts},
            repo_root=tmp_path,
            today=date(2026, 8, 31),
        )
        == []
    )

    target.write_bytes(future_content)

    assert (
        matching_waiver(
            _finding(),
            package=waiver.package,
            manifest=manifest,
            repo_root=tmp_path,
            today=date(2026, 8, 31),
        )
        is waiver
    )
    assert (
        validate_manifest_against_facts(
            manifest,
            facts_by_package={waiver.package: facts},
            repo_root=tmp_path,
            today=date(2026, 8, 31),
        )
        == []
    )


def test_matching_waiver_rejects_symlinked_package_outside_repository(tmp_path: Path) -> None:
    external_root = tmp_path.parent / f"{tmp_path.name}-external"
    external_target, digest = _write_target(external_root)
    public_root = tmp_path / "skills/public"
    public_root.mkdir(parents=True)
    (public_root / "demo").symlink_to(external_target.parents[1], target_is_directory=True)

    assert (
        matching_waiver(
            _finding(),
            package="skills/public/demo",
            manifest=WaiverManifest((_waiver(digest=digest),)),
            repo_root=tmp_path,
            today=date(2026, 8, 31),
        )
        is None
    )


def test_expired_waiver_is_rejected_and_does_not_match(tmp_path: Path) -> None:
    _, digest = _write_target(tmp_path)
    waiver = _waiver(digest=digest, expires_on=date(2026, 8, 30))
    manifest = WaiverManifest((waiver,))
    facts = {"findings": [_finding()]}

    errors = validate_manifest_against_facts(
        manifest,
        facts_by_package={waiver.package: facts},
        repo_root=tmp_path,
        today=date(2026, 8, 31),
    )

    assert len(errors) == 1
    assert "expired on 2026-08-30" in errors[0]
    assert matching_waiver(_finding(), package=waiver.package, manifest=manifest, repo_root=tmp_path, today=date(2026, 8, 31)) is None


def test_manifest_validation_refuses_blocker_waiver(tmp_path: Path) -> None:
    _, digest = _write_target(tmp_path)
    waiver = _waiver(digest=digest)

    errors = validate_manifest_against_facts(
        WaiverManifest((waiver,)),
        facts_by_package={waiver.package: {"findings": [_finding(severity="blocker")]}},
        repo_root=tmp_path,
        today=date(2026, 8, 31),
    )

    assert "blockers can never be waived" in errors[0]


def test_pr_head_manifest_is_validated_but_cannot_self_apply(tmp_path: Path, monkeypatch) -> None:
    _, digest = _write_target(tmp_path)
    proposed = WaiverManifest((_waiver(digest=digest),))
    loaded: list[tuple[str, str]] = []

    def fake_load(repo_root: Path, ref: str, *, label: str) -> WaiverManifest:
        loaded.append((ref, label))
        return EMPTY_MANIFEST if label == "trusted base" else proposed

    monkeypatch.setattr(runner, "load_manifest_at_ref", fake_load)
    args = SimpleNamespace(base_ref="base-sha", head_ref="head-sha", before=None, after=None)

    effective, head = runner.load_waiver_manifests(args, tmp_path)

    assert effective is EMPTY_MANIFEST
    assert head is proposed
    assert loaded == [("base-sha", "trusted base"), ("head-sha", "proposed head")]


def test_main_fails_closed_on_malformed_head_manifest(tmp_path: Path, monkeypatch, capsys) -> None:
    def fail_load(args, repo_root):
        raise WaiverManifestError("proposed head: invalid JSON")

    monkeypatch.setattr(runner, "load_waiver_manifests", fail_load)
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: pytest.fail("diff must not run"))

    exit_code = runner.main(["--base-ref", "base", "--head-ref", "head", "--repo-root", str(tmp_path)])

    assert exit_code == 1
    assert "Invalid waiver manifest" in capsys.readouterr().err


def test_workflow_triggers_on_waiver_implementation_and_manifest() -> None:
    workflow = (REPO_ROOT / ".github/workflows/skill-review-ci.yml").read_text(encoding="utf-8")

    assert workflow.count('"scripts/skill_review_waivers.py"') == 2
    assert workflow.count('".github/skill-review-waivers.v1.json"') == 2


def test_run_review_keeps_waived_error_visible_and_passes(tmp_path: Path, monkeypatch, capsys) -> None:
    package = tmp_path / "skills/public/demo"
    _, digest = _write_target(tmp_path)
    facts = {
        "summary": {"blockers": 0, "errors": 1, "warnings": 0, "infos": 0},
        "completeness": {"not_assessed": []},
        "findings": [_finding()],
    }
    monkeypatch.setattr(runner, "collect_review_facts", lambda *args: facts)

    exit_code = runner.run_review(package, tmp_path, "python", WaiverManifest((_waiver(digest=digest),)))

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "- error python-subprocess" in output
    assert "[WAIVED until 2027-02-28:" in output
    assert "Passed: skills/public/demo (1 waived finding(s))" in output


def test_run_review_still_fails_for_unwaived_error(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "skills/public/demo"
    _write_target(tmp_path)
    facts = {
        "summary": {"blockers": 0, "errors": 1, "warnings": 0, "infos": 0},
        "completeness": {"not_assessed": []},
        "findings": [_finding()],
    }
    monkeypatch.setattr(runner, "collect_review_facts", lambda *args: facts)

    assert runner.run_review(package, tmp_path, "python", EMPTY_MANIFEST) == 1
