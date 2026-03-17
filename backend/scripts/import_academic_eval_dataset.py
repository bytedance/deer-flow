#!/usr/bin/env python3
"""One-click importer for raw accept/reject datasets.

Usage examples:
  # single file
  uv run python scripts/import_academic_eval_dataset.py \
    --input /path/to/raw.json \
    --dataset-name top_tier_accept_reject_real \
    --dataset-version 2026_03

  # batch directory import
  uv run python scripts/import_academic_eval_dataset.py \
    --input /path/to/raw_dir \
    --dataset-name top_tier_accept_reject_real \
    --dataset-version 2026_03 \
    --batch-pattern "*.json"

  # validation only (no import)
  uv run python scripts/import_academic_eval_dataset.py \
    --input /path/to/raw_dir \
    --dataset-name top_tier_accept_reject_real \
    --dataset-version 2026_03 \
    --validate-only

  # import with auto-fix preprocessor
  uv run python scripts/import_academic_eval_dataset.py \
    --input /path/to/raw_dir \
    --dataset-name top_tier_accept_reject_real \
    --dataset-version 2026_03 \
    --autofix \
    --autofix-level balanced
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _slugify(value: str, *, default: str = "dataset") -> str:
    raw = (value or "").strip().lower()
    out: list[str] = []
    for ch in raw:
        if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in {"_", "-", "."}:
            out.append(ch)
        else:
            out.append("-")
    text = "".join(out).strip("-")
    while "--" in text:
        text = text.replace("--", "-")
    return text or default


def _write_json(path: Path, payload: dict[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, payload: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _collect_input_files(input_path: Path, *, batch_pattern: str) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    files = sorted(p for p in input_path.glob(batch_pattern) if p.is_file())
    if not files:
        raise FileNotFoundError(
            f"No files matched batch pattern '{batch_pattern}' in {input_path}"
        )
    return files


def _build_effective_dataset_name(
    *,
    base_dataset_name: str,
    dataset_version: str,
    source_file: Path,
    multi_file: bool,
    append_version_to_name: bool,
) -> str:
    name = _slugify(base_dataset_name, default="accept_reject_real")
    if append_version_to_name:
        name = _slugify(f"{name}_{dataset_version}", default=name)
    if multi_file:
        name = _slugify(f"{name}_{source_file.stem}", default=name)
    return name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import raw accept/reject JSON into normalized versioned eval dataset(s).",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Raw dataset file path or a directory for batch import.",
    )
    parser.add_argument(
        "--dataset-name",
        required=True,
        help="Base dataset name, e.g. top_tier_accept_reject_real.",
    )
    parser.add_argument(
        "--dataset-version",
        default="v1",
        help="Dataset version label, e.g. 2026_03.",
    )
    parser.add_argument(
        "--benchmark-split",
        default="",
        help="Optional benchmark split override (single file recommended).",
    )
    parser.add_argument(
        "--source-name",
        default="",
        help="Optional source name shown in metadata, e.g. top-tier-anon-corpus.",
    )
    parser.add_argument(
        "--output-dir",
        default="src/evals/academic/datasets",
        help="Output directory for imported dataset + manifest files.",
    )
    parser.add_argument(
        "--batch-pattern",
        default="*.json",
        help="Glob used when --input is a directory. Default: *.json",
    )
    parser.add_argument(
        "--append-version-to-name",
        action="store_true",
        default=True,
        help="Append dataset_version to output dataset_name (default: true).",
    )
    parser.add_argument(
        "--no-append-version-to-name",
        action="store_false",
        dest="append_version_to_name",
        help="Do not append dataset_version to output dataset_name.",
    )
    parser.add_argument(
        "--anonymize",
        action="store_true",
        default=True,
        help="Enable anonymization (default: true).",
    )
    parser.add_argument(
        "--no-anonymize",
        action="store_false",
        dest="anonymize",
        help="Disable anonymization.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Fail immediately when a record cannot be normalized.",
    )
    parser.add_argument(
        "--autofix",
        action="store_true",
        default=False,
        help="Apply low-risk pre-import auto-fixes before validation/import.",
    )
    parser.add_argument(
        "--autofix-level",
        choices=("safe", "balanced", "aggressive"),
        default="balanced",
        help="Auto-fix whitelist level. Default: balanced.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        default=False,
        help="Only run pre-import validation and emit reports (skip dataset import).",
    )
    parser.add_argument(
        "--fail-on-validation-errors",
        action="store_true",
        default=False,
        help="Fail if pre-import validation finds any errors.",
    )
    parser.add_argument(
        "--validation-report-mode",
        choices=("json", "markdown", "both"),
        default="both",
        help="Validation report output format. Default: both.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Allow overwriting existing output files.",
    )
    return parser


def main() -> int:
    from src.evals.academic.importer import import_accept_reject_payload
    from src.evals.academic.preprocessor import (
        preprocess_accept_reject_dataset,
        render_autofix_report_markdown,
    )
    from src.evals.academic.validator import (
        render_validation_report_markdown,
        validate_accept_reject_payload,
    )

    args = build_parser().parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path.cwd() / output_dir).resolve()

    files = _collect_input_files(input_path, batch_pattern=args.batch_pattern)
    multi_file = len(files) > 1
    imported_rows: list[dict[str, Any]] = []

    for source_file in files:
        effective_name = _build_effective_dataset_name(
            base_dataset_name=args.dataset_name,
            dataset_version=args.dataset_version,
            source_file=source_file,
            multi_file=multi_file,
            append_version_to_name=args.append_version_to_name,
        )
        effective_split: str | None
        if args.benchmark_split:
            effective_split = (
                _slugify(
                    f"{args.benchmark_split}_{source_file.stem}",
                    default=args.benchmark_split,
                )
                if multi_file
                else args.benchmark_split
            )
        else:
            effective_split = None

        raw_payload = json.loads(source_file.read_text(encoding="utf-8"))
        effective_payload = raw_payload
        autofix_report: dict[str, Any] | None = None
        autofix_input_file: Path | None = None
        autofix_json_file: Path | None = None
        autofix_markdown_file: Path | None = None
        if args.autofix:
            preprocessed = preprocess_accept_reject_dataset(
                source_file,
                apply_autofix=True,
                autofix_level=args.autofix_level,
            )
            effective_payload = preprocessed["fixed_payload"]
            autofix_report = preprocessed["report"]
            autofix_input_file = output_dir / f"{effective_name}.autofix.input.json"
            autofix_json_file = output_dir / f"{effective_name}.autofix.report.json"
            autofix_markdown_file = output_dir / f"{effective_name}.autofix.report.md"
            _write_json(autofix_input_file, effective_payload, overwrite=args.overwrite)
            _write_json(
                autofix_json_file,
                autofix_report,
                overwrite=args.overwrite,
            )
            _write_text(
                autofix_markdown_file,
                render_autofix_report_markdown(autofix_report),
                overwrite=args.overwrite,
            )

        validation = validate_accept_reject_payload(
            effective_payload,
            source_path_label=str(source_file),
        )
        validation_json_file = output_dir / f"{effective_name}.validation.json"
        validation_markdown_file = output_dir / f"{effective_name}.validation.md"
        if args.validation_report_mode in {"json", "both"}:
            _write_json(
                validation_json_file,
                validation,
                overwrite=args.overwrite,
            )
        if args.validation_report_mode in {"markdown", "both"}:
            _write_text(
                validation_markdown_file,
                render_validation_report_markdown(validation),
                overwrite=args.overwrite,
            )
        validation_errors = int(validation.get("error_count", 0))
        validation_warnings = int(validation.get("warning_count", 0))
        if (
            args.strict
            or args.fail_on_validation_errors
        ) and validation_errors > 0:
            raise ValueError(
                "Validation failed for "
                f"{source_file}: {validation_errors} error(s), "
                f"{validation_warnings} warning(s)"
            )

        if args.validate_only:
            imported_rows.append(
                {
                    "input": str(source_file),
                    "dataset_name": effective_name,
                    "dataset_version": args.dataset_version,
                    "validation_status": validation.get("status", "unknown"),
                    "validation_error_count": validation_errors,
                    "validation_warning_count": validation_warnings,
                    "validation_json_file": str(validation_json_file),
                    "validation_markdown_file": str(validation_markdown_file),
                    "autofix_applied": args.autofix,
                    "autofix_level": args.autofix_level if args.autofix else None,
                    "autofix_modified_record_count": int(
                        (autofix_report or {}).get("modified_record_count") or 0
                    ),
                    "autofix_input_file": str(autofix_input_file) if autofix_input_file else None,
                    "autofix_report_file": str(autofix_json_file) if autofix_json_file else None,
                    "autofix_markdown_file": str(autofix_markdown_file) if autofix_markdown_file else None,
                }
            )
            continue

        imported = import_accept_reject_payload(
            effective_payload,
            source_path_label=str(source_file),
            dataset_name=effective_name,
            dataset_version=args.dataset_version,
            benchmark_split=effective_split,
            source_name=args.source_name or None,
            anonymize=args.anonymize,
            strict=args.strict,
            source_fingerprint=validation.get("source_fingerprint"),
        )
        dataset_file = output_dir / f"{imported['dataset_name']}.json"
        manifest_file = output_dir / f"{imported['dataset_name']}.manifest.json"
        _write_json(dataset_file, imported["dataset_payload"], overwrite=args.overwrite)
        _write_json(
            manifest_file,
            imported["manifest_payload"],
            overwrite=args.overwrite,
        )

        imported_rows.append(
            {
                "input": str(source_file),
                "dataset_name": imported["dataset_name"],
                "dataset_version": imported["dataset_version"],
                "dataset_file": str(dataset_file),
                "manifest_file": str(manifest_file),
                "imported_case_count": imported["imported_case_count"],
                "accepted_case_count": imported["accepted_case_count"],
                "rejected_case_count": imported["rejected_case_count"],
                "skipped_case_count": imported["skipped_case_count"],
                "warnings": imported["warnings"],
                "validation_status": validation.get("status", "unknown"),
                "validation_error_count": validation_errors,
                "validation_warning_count": validation_warnings,
                "validation_json_file": str(validation_json_file),
                "validation_markdown_file": str(validation_markdown_file),
                "autofix_applied": args.autofix,
                "autofix_level": args.autofix_level if args.autofix else None,
                "autofix_modified_record_count": int(
                    (autofix_report or {}).get("modified_record_count") or 0
                ),
                "autofix_input_file": str(autofix_input_file) if autofix_input_file else None,
                "autofix_report_file": str(autofix_json_file) if autofix_json_file else None,
                "autofix_markdown_file": str(autofix_markdown_file) if autofix_markdown_file else None,
            }
        )

    summary = {
        "imported_at": datetime.now(UTC).isoformat(),
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "file_count": len(imported_rows),
        "validate_only": args.validate_only,
        "autofix": args.autofix,
        "autofix_level": args.autofix_level if args.autofix else None,
        "rows": imported_rows,
    }
    summary_file = output_dir / (
        f"import-summary-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    )
    _write_json(summary_file, summary, overwrite=args.overwrite)

    print(
        json.dumps(
            {
                "ok": True,
                "file_count": len(imported_rows),
                "output_dir": str(output_dir),
                "summary_file": str(summary_file),
                "dataset_names": [row["dataset_name"] for row in imported_rows],
                "validate_only": args.validate_only,
                "autofix": args.autofix,
                "autofix_level": args.autofix_level if args.autofix else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

