"""Chart-visualization CLI regressions: spreadsheet mapping and nonzero failures.

The AntV request is mocked with a Node ``--require`` preload so the test stays
offline. Successful chart URLs stay on stdout; diagnostics stay on stderr.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "skills" / "public" / "chart-visualization" / "scripts" / "generate.js"
SKILL = REPO_ROOT / "skills" / "public" / "chart-visualization" / "SKILL.md"
NODE = shutil.which("node")

FETCH_PRELOAD = """\
const fs = require("fs");

global.fetch = async (url, options) => {
  const capture = process.env.CHART_VIS_CAPTURE;
  if (capture) {
    fs.appendFileSync(
      capture,
      JSON.stringify({ url: String(url), body: options && options.body }) + "\\n",
    );
  }
  const status = Number(process.env.CHART_VIS_HTTP_STATUS || 200);
  if (status >= 400) {
    return {
      ok: false,
      status,
      text: async () => "upstream failed",
      json: async () => ({}),
    };
  }
  return {
    ok: true,
    status: 200,
    text: async () => "",
    json: async () => ({
      success: true,
      resultObj: "https://example.test/sheet.png",
    }),
  };
};
"""


pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to run generate.js")


def _run(tmp_path, spec, *, http_status=None):
    preload = tmp_path / "mock_fetch.js"
    preload.write_text(FETCH_PRELOAD, encoding="utf-8")
    capture = tmp_path / "capture.jsonl"
    env = os.environ.copy()
    env["CHART_VIS_CAPTURE"] = str(capture)
    env["VIS_REQUEST_SERVER"] = "http://127.0.0.1:9/api/gpt-vis"
    env.pop("SERVICE_ID", None)
    if http_status is None:
        env.pop("CHART_VIS_HTTP_STATUS", None)
    else:
        env["CHART_VIS_HTTP_STATUS"] = str(http_status)

    result = subprocess.run(
        [NODE, "--require", str(preload), str(SCRIPT), json.dumps(spec)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        env=env,
    )
    calls = []
    if capture.exists():
        calls = [json.loads(line) for line in capture.read_text(encoding="utf-8").splitlines() if line]
    return result, calls


def _chart_type_map():
    probe = subprocess.run(
        [
            NODE,
            "-e",
            "const {CHART_TYPE_MAP}=require(process.argv[1]); process.stdout.write(JSON.stringify(CHART_TYPE_MAP));",
            str(SCRIPT),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert probe.returncode == 0, probe.stderr
    return json.loads(probe.stdout)


def test_generate_spreadsheet_is_mapped_and_prints_url(tmp_path):
    chart_types = _chart_type_map()
    skill = SKILL.read_text(encoding="utf-8-sig")
    assert "26 available options" in skill
    assert len(chart_types) == 26
    assert chart_types["generate_spreadsheet"] == "spreadsheet"

    spec = {
        "tool": "generate_spreadsheet",
        "args": {"data": [{"name": "Jane", "age": 25}], "title": "People"},
    }
    result, calls = _run(tmp_path, spec)

    assert result.returncode == 0
    assert result.stdout == "https://example.test/sheet.png\n"
    assert result.stderr == ""
    assert "Unknown tool" not in result.stderr
    assert len(calls) == 1
    body = json.loads(calls[0]["body"])
    assert body["type"] == "spreadsheet"
    assert body["source"] == "chart-visualization-creator"
    assert body["data"] == [{"name": "Jane", "age": 25}]
    assert body["title"] == "People"
    assert calls[0]["url"] == "http://127.0.0.1:9/api/gpt-vis"


def test_unknown_tool_exits_nonzero_without_calling_the_service(tmp_path):
    result, calls = _run(tmp_path, {"tool": "generate_not_a_chart", "args": {}})

    assert result.returncode == 1
    assert result.stdout == ""
    assert "Unknown tool 'generate_not_a_chart'" in result.stderr
    assert calls == []


def test_missing_tool_exits_nonzero(tmp_path):
    result, calls = _run(tmp_path, {"args": {"data": []}})

    assert result.returncode == 1
    assert result.stdout == ""
    assert "tool" in result.stderr
    assert calls == []


def test_http_failure_exits_nonzero(tmp_path):
    spec = {"tool": "generate_spreadsheet", "args": {"data": [{"name": "Jane"}]}}
    result, calls = _run(tmp_path, spec, http_status=502)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "HTTP 502" in result.stderr
    assert len(calls) == 1
    assert json.loads(calls[0]["body"])["type"] == "spreadsheet"


def test_batch_keeps_successful_urls_and_still_exits_nonzero(tmp_path):
    spec = [
        {"tool": "generate_not_a_chart"},
        {"tool": "generate_spreadsheet", "args": {"data": [{"name": "Ada"}]}},
    ]
    result, calls = _run(tmp_path, spec)

    assert result.returncode == 1
    assert result.stdout == "https://example.test/sheet.png\n"
    assert "Unknown tool 'generate_not_a_chart'" in result.stderr
    assert len(calls) == 1
    assert json.loads(calls[0]["body"])["type"] == "spreadsheet"
