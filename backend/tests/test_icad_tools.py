from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from deerflow.reflection import resolve_variable


def _make_runtime(outputs_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        state={
            "thread_data": {
                "outputs_path": outputs_path,
                "workspace_path": str(Path(outputs_path).parent / "workspace"),
                "uploads_path": str(Path(outputs_path).parent / "uploads"),
            }
        },
        context={"thread_id": "thread-1"},
        config={},
    )


def test_visualize_tool_can_be_resolved():
    tool = resolve_variable("icad.tools:visualize_steel_structure")

    assert tool.name == "visualize_steel_structure"


def test_visualize_tool_materializes_worker_artifacts(tmp_path, monkeypatch):
    tool_module = importlib.import_module("icad.tools.visualize_structure")

    outputs_dir = tmp_path / "threads" / "thread-1" / "user-data" / "outputs"
    outputs_dir.mkdir(parents=True)

    def _fake_visualize_origin_data(*, origin_data_json: str, model_name: str | None, output_dir: Path, artifact_prefix: str | None):
        assert origin_data_json == '{"version":"v6.1.2"}'
        assert model_name == "厂房模型"
        assert output_dir == outputs_dir
        assert artifact_prefix == "plant-a"
        return {
            "model_name": "厂房模型",
            "apf_issues": [],
            "apf_issue_summary": {"total": 0, "warningCount": 0, "errorCount": 0},
            "artifacts": {
                "vsfx_path": str(outputs_dir / "plant-a.vsfx"),
                "cda_json_path": str(outputs_dir / "plant-a.cda.json"),
                "properties_json_path": str(outputs_dir / "plant-a.properties.json"),
            },
        }

    monkeypatch.setattr(tool_module, "visualize_origin_data", _fake_visualize_origin_data)

    result = tool_module.visualize_steel_structure.func(
        runtime=_make_runtime(str(outputs_dir)),
        origin_data_json='{"version":"v6.1.2"}',
        model_name="厂房模型",
        artifact_prefix="plant-a",
    )

    payload = json.loads(result)
    assert payload["modelName"] == "厂房模型"
    assert payload["artifacts"]["vsfx"] == str(outputs_dir / "plant-a.vsfx")
    assert payload["artifacts"]["cdaJson"] == str(outputs_dir / "plant-a.cda.json")
    assert payload["artifacts"]["propertiesJson"] == str(outputs_dir / "plant-a.properties.json")


def test_visualize_service_writes_inline_worker_artifacts(tmp_path, monkeypatch):
    service_module = importlib.import_module("icad.tools.service")
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "success": True,
                "data": {
                    "modelName": "可视化模型",
                    "apfIssues": [],
                    "apfIssueSummary": {"total": 0, "warningCount": 0, "errorCount": 0},
                    "artifacts": {
                        "vsfx": {
                            "filename": "model.vsfx",
                            "mimeType": "application/vsfx",
                            "base64": "dnNmeA==",
                        },
                        "cdaJson": {
                            "filename": "cda.json",
                            "content": [{"name": "root"}],
                        },
                        "propertiesJson": {
                            "filename": "properties.json",
                            "content": [{"name": "section"}],
                        },
                    },
                },
            }

    monkeypatch.setattr(
        service_module.httpx,
        "post",
        lambda *args, **kwargs: _FakeResponse(),
    )
    monkeypatch.setattr(service_module, "_worker_base_url", lambda: "http://127.0.0.1:8000")
    monkeypatch.setattr(service_module, "_worker_timeout_seconds", lambda: 12.0)

    result = service_module.visualize_origin_data(
        origin_data_json='{"version":"v6.1.2"}',
        model_name="可视化模型",
        output_dir=output_dir,
        artifact_prefix="demo",
    )

    assert (output_dir / "demo.vsfx").read_bytes() == b"vsfx"
    assert json.loads((output_dir / "demo.cda.json").read_text(encoding="utf-8")) == [{"name": "root"}]
    assert json.loads((output_dir / "demo.properties.json").read_text(encoding="utf-8")) == [{"name": "section"}]
    assert result["artifacts"]["vsfx_path"] == str(output_dir / "demo.vsfx")


def test_project_config_template_exposes_visualize_tool():
    config_path = Path(__file__).resolve().parents[2] / "config.example.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert any(group.get("name") == "icad" for group in config["tool_groups"])
    assert any(
        tool.get("name") == "visualize_steel_structure"
        and tool.get("use") == "icad.tools:visualize_steel_structure"
        for tool in config["tools"]
    )
