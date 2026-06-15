"""Direct report executor — orchestrates Skill script calls for builtin reports."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from deerflow.config import get_app_config
from deerflow.report_executor.errors import NoDataError, ScriptFailedError
from deerflow.report_templates.records import new_report_run_id


class DirectReportExecutor:
    """Executes builtin reports by directly calling Skill scripts.

    Bypasses DSL state machine, directly orchestrating:
    - query_*.py (fetch data)
    - *_kpi.py (compute KPIs)
    - export_report.py (generate artifacts)
    """

    SCRIPT_MAP = {
        "daily": {
            "query": "query_daily.py",
            "kpi": "daily_kpi.py",
            "export": "export_report.py",
            "skill": "daily-report",
        },
        "weekly": {
            "query": "query_weekly.py",
            "kpi": "weekly_kpi.py",
            "export": "export_report.py",
            "skill": "weekly-report",
        },
        "monthly": {
            "query": "query_monthly.py",
            "kpi": "monthly_kpi.py",
            "export": "export_report.py",
            "skill": "monthly-report",
        },
    }

    def __init__(self, output_dir: str = "/mnt/user-data/outputs", skills_root: str | None = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if skills_root is not None:
            self._skills_root = skills_root
        else:
            try:
                self._skills_root = str(get_app_config().skills.get_skills_path())
            except Exception:
                self._skills_root = "/mnt/skills"

    def execute(
        self,
        report_type: str,
        scope: dict[str, Any],
        equipment_type: str = "all",
        compare_with: str | None = None,
        equipment_ids: list[str] | None = None,
        equipment_labels: list[str] | None = None,
        kpi_keys: list[str] | None = None,
        equipment_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a builtin report.

        Args:
            report_type: "daily" | "weekly" | "monthly"
            scope: {report_date} / {week_start, date_end} / {report_month}
            equipment_type: "all" | "static_equipment" | "rotating_machinery" | "pump" | "reciprocating_machinery"
            compare_with: "previous_day" | "previous_week" | "previous_month" | "none" | None
            equipment_ids: List of device IDs (None = all devices)
            equipment_labels: List of device names (parallel to equipment_ids)
            kpi_keys: List of KPI keys (None = template defaults)
            equipment_meta: Equipment metadata dict {id: {id, name, ...}} for org tree passthrough

        Returns:
            {report_run_id, artifacts: [{path, type}], status}

        Raises:
            ScriptFailedError: When a script fails
            NoDataError: When data script returns empty results
        """
        if report_type not in self.SCRIPT_MAP:
            raise ValueError(f"Unknown report_type: {report_type}")

        report_run_id = new_report_run_id()
        self._current_run_id = report_run_id
        scripts = self.SCRIPT_MAP[report_type]
        skill_dir = f"{self._skills_root}/custom/{scripts['skill']}/scripts"

        artifacts = []

        try:
            data_file = self._run_query_script(
                skill_dir=skill_dir,
                query_script=scripts["query"],
                report_type=report_type,
                scope=scope,
                equipment_type=equipment_type,
                compare_with=compare_with,
                equipment_ids=equipment_ids,
                equipment_labels=equipment_labels,
                kpi_keys=kpi_keys,
                equipment_meta=equipment_meta,
            )
            artifacts.append({"path": str(data_file), "type": "data"})

            kpi_file = self._run_kpi_script(
                skill_dir=skill_dir,
                kpi_script=scripts["kpi"],
                data_file=data_file,
            )
            artifacts.append({"path": str(kpi_file), "type": "kpi"})

            report_file = self._run_export_script(
                skill_dir=skill_dir,
                export_script=scripts["export"],
                kpi_file=kpi_file,
                report_type=report_type,
            )
            artifacts.append({"path": str(report_file), "type": "report"})

        except (ScriptFailedError, NoDataError):
            raise
        except Exception as e:
            raise ScriptFailedError(str(e), step="unknown") from e

        return {
            "report_run_id": report_run_id,
            "artifacts": artifacts,
            "status": "success",
        }

    def _run_query_script(
        self,
        skill_dir: str,
        query_script: str,
        report_type: str,
        scope: dict[str, Any],
        equipment_type: str,
        compare_with: str | None,
        equipment_ids: list[str] | None,
        equipment_labels: list[str] | None,
        kpi_keys: list[str] | None,
        equipment_meta: dict[str, Any] | None = None,
    ) -> Path:
        """Run query_*.py script and return output data file path.

        The script writes actual data to its own output path and prints a metadata
        envelope ``{"output": "<path>", ...}`` to stdout. We parse the ``output``
        field to locate the real data file instead of overwriting it with stdout.
        """
        cmd = ["python", f"{skill_dir}/{query_script}"]

        cmd.extend(self._build_scope_args(report_type, scope))
        cmd.extend(["--type", equipment_type])

        if compare_with:
            cmd.extend(["--compare", compare_with])

        if equipment_ids:
            cmd.extend(["--equipment", ",".join(equipment_ids)])
            if equipment_labels:
                cmd.extend(["--equipment-names", ",".join(equipment_labels)])
        else:
            cmd.extend(["--scope", "all"])

        if kpi_keys:
            cmd.extend(["--kpis", ",".join(kpi_keys)])

        if equipment_meta:
            meta_records = list(equipment_meta.values())
            meta_payload = {"equipment_type": equipment_type, "records": meta_records, **equipment_meta}
            cmd.extend(["--equipment-meta", json.dumps(meta_payload, ensure_ascii=False)])

        stdout = self._run_subprocess(cmd, step=query_script)
        self._validate_script_output(stdout, step=query_script)

        return self._resolve_output_path(stdout, step=query_script, fallback=self.output_dir / f"{report_type}_data.json")

    def _build_scope_args(self, report_type: str, scope: dict[str, Any]) -> list[str]:
        """Build command-line args for scope based on report type."""
        if report_type == "daily":
            return ["--date", scope["report_date"]]
        elif report_type == "weekly":
            return ["--week-start", scope["week_start"]]
        elif report_type == "monthly":
            return ["--report-month", scope["report_month"]]
        else:
            raise ValueError(f"Unknown report_type: {report_type}")

    def _run_kpi_script(self, skill_dir: str, kpi_script: str, data_file: Path) -> Path:
        """Run *_kpi.py script and return output KPI file path."""
        kpi_file = self.output_dir / data_file.name.replace("_data.json", "_kpi.json")

        cmd = [
            "python",
            f"{skill_dir}/{kpi_script}",
            "--input",
            str(data_file),
            "--output",
            str(kpi_file),
        ]

        stdout = self._run_subprocess(cmd, step=kpi_script)
        self._validate_script_output(stdout, step=kpi_script)

        return self._resolve_output_path(stdout, step=kpi_script, fallback=kpi_file)

    def _run_export_script(
        self,
        skill_dir: str,
        export_script: str,
        kpi_file: Path,
        report_type: str,
    ) -> Path:
        """Run export_report.py script and return output report file path."""
        report_file = self.output_dir / f"{report_type}_report.md"

        cmd = [
            "python",
            f"{skill_dir}/{export_script}",
            "--input",
            str(kpi_file),
            "--output",
            str(report_file),
        ]

        stdout = self._run_subprocess(cmd, step=export_script)
        self._validate_script_output(stdout, step=export_script)

        return self._resolve_output_path(stdout, step=export_script, fallback=report_file)

    def _run_subprocess(self, cmd: list[str], step: str) -> str:
        """Run subprocess and return stdout."""
        env = {
            **os.environ,
            "DAILY_REPORT_OUTPUT_DIR": str(self.output_dir),
            "REPORT_RUN_ID": getattr(self, "_current_run_id", ""),
            "FEATURES_TOOL_ROOT": f"{self._skills_root}/custom/features-tool",
        }
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
                env=env,
            )

            if result.returncode != 0:
                raise ScriptFailedError(
                    f"Script {step} exited with code {result.returncode}: {result.stderr}",
                    step=step,
                    stdout=result.stdout,
                )

            return result.stdout

        except subprocess.TimeoutExpired as e:
            raise ScriptFailedError(f"Script {step} timed out", step=step) from e
        except Exception as e:
            if isinstance(e, ScriptFailedError):
                raise
            raise ScriptFailedError(f"Failed to run {step}: {e}", step=step) from e

    def _validate_script_output(self, stdout: str, step: str) -> None:
        """Validate script output JSON."""
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise ScriptFailedError(f"Script {step} output is not valid JSON", step=step, stdout=stdout) from e

        if isinstance(data, dict) and "error" in data:
            error_msg = data["error"]
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            raise ScriptFailedError(f"Script {step} returned error: {error_msg}", step=step, stdout=stdout)

        if isinstance(data, dict) and not data:
            raise NoDataError(f"Script {step} returned empty data", step=step)

    def _resolve_output_path(self, stdout: str, step: str, fallback: Path) -> Path:
        """Resolve the actual output file path from script stdout metadata.

        Scripts write data to their own output path and print
        ``{"output": "<path>", ...}`` to stdout. This method extracts the
        ``output`` field. If absent or the referenced file does not exist,
        falls back to the pre-computed path.
        """
        try:
            metadata = json.loads(stdout)
        except json.JSONDecodeError:
            return fallback

        if not isinstance(metadata, dict):
            return fallback

        output_str = metadata.get("output")
        if not output_str:
            return fallback

        resolved = Path(output_str)
        if not resolved.is_file():
            raise ScriptFailedError(
                f"Script {step} output path does not exist: {resolved}",
                step=step,
                stdout=stdout,
            )
        return resolved
