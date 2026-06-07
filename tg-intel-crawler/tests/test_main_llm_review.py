"""End-to-end-ish tests for `tg-crawler candidates llm-review`.

We mock the LLM client (so no real API), the TGClient (so no real Telegram),
and use tmp_path for the candidate yaml + output dirs.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from tg_intel_crawler.main import cli


def _seed_config(tmp_path: Path, candidates_path: Path) -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "telegram": {"api_id": 1, "api_hash": "x", "phone": "+1", "session_name": "s"},
        "llm": {"api_key": "k", "base_url": "https://example.com/v1",
                "model": "ep-test", "batch_size": 5},
        "crawl": {"delay_min": 0, "delay_max": 0, "history_days": 7, "download_media": False},
        "output": {"dir": str(tmp_path / "output"), "format": ["json"]},
        "groups": [],
        "discovery": {"candidates_path": str(candidates_path)},
        "join": {"min_interval": 0, "max_interval": 0, "daily_limit": 5},
    }, allow_unicode=True), encoding="utf-8")
    return cfg_path


def _seed_candidates(path: Path):
    payload = {"candidates": {
        "douyinhao88": {
            "invite_hash": None,
            "first_seen": "2026-06-05T00:00:00+00:00",
            "last_seen":  "2026-06-08T00:00:00+00:00",
            "count": 7,
            "status": "pending",
            "sources": [{"group": "卖号群", "msg_id": 100, "channel": "text"}],
        },
    }}
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")


def test_auto_join_without_write_config_errors(tmp_path, monkeypatch):
    cands = tmp_path / "discovered_groups.yaml"
    _seed_candidates(cands)
    cfg = _seed_config(tmp_path, cands)
    monkeypatch.setattr("tg_intel_crawler.main.CONFIG_PATH", cfg)

    runner = CliRunner()
    result = runner.invoke(cli, ["candidates", "llm-review", "--auto-join"])
    assert result.exit_code != 0
    assert "--auto-join requires --write-config" in result.output


def _make_mock_llm(stage1_advance=True, stage2_approve=True):
    """Returns a function that produces an LLM client whose responses match
    the stage we're hitting."""
    stage1_payload = json.dumps([
        {"index": 0,
         "decision": "advance" if stage1_advance else "reject",
         "confidence": "high", "reason": "ok"},
    ])
    stage2_payload = json.dumps({
        "decision": "approve" if stage2_approve else "reject",
        "confidence": "high",
        "risk_type": "账号交易",
        "reason": "明确卖号",
    })
    client = MagicMock()
    # Stage1 happens first; stage2 follows. Use side_effect list.
    client.chat.completions.create = AsyncMock(side_effect=[
        MagicMock(choices=[MagicMock(message=MagicMock(content=stage1_payload))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content=stage2_payload))]),
    ])
    return client


def test_dry_run_does_not_write_verdict_or_change_status(tmp_path, monkeypatch):
    cands = tmp_path / "discovered_groups.yaml"
    _seed_candidates(cands)
    cfg = _seed_config(tmp_path, cands)
    monkeypatch.setattr("tg_intel_crawler.main.CONFIG_PATH", cfg)

    fake_client = _make_mock_llm(stage1_advance=True, stage2_approve=True)
    monkeypatch.setattr(
        "tg_intel_crawler.filter.candidate_reviewer.AsyncOpenAI",
        lambda **kw: fake_client,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["candidates", "llm-review", "--dry-run"])
    assert result.exit_code == 0, result.output

    raw = yaml.safe_load(cands.read_text(encoding="utf-8"))
    entry = raw["candidates"]["douyinhao88"]
    assert "llm_verdict" not in entry
    assert entry["status"] == "pending"


def _seed_raw_message(tmp_path: Path, group: str = "卖号群", msg_id: int = 100,
                      text: str = "出抖音老号 联系 @douyinhao88"):
    """Drop a raw message file so RawMessageLookup finds the source text."""
    raw_dir = tmp_path / "output" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"2026-06-08_{group}.json").write_text(
        json.dumps([{
            "msg_id": msg_id,
            "group_name": group,
            "text": text,
            "date": "2026-06-08T00:00:00+00:00",
        }], ensure_ascii=False),
        encoding="utf-8",
    )


def test_review_writes_verdict_to_yaml(tmp_path, monkeypatch):
    cands = tmp_path / "discovered_groups.yaml"
    _seed_candidates(cands)
    cfg = _seed_config(tmp_path, cands)
    _seed_raw_message(tmp_path)
    monkeypatch.setattr("tg_intel_crawler.main.CONFIG_PATH", cfg)

    fake_client = _make_mock_llm(stage1_advance=True, stage2_approve=True)
    monkeypatch.setattr(
        "tg_intel_crawler.filter.candidate_reviewer.AsyncOpenAI",
        lambda **kw: fake_client,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["candidates", "llm-review"])
    assert result.exit_code == 0, result.output

    raw = yaml.safe_load(cands.read_text(encoding="utf-8"))
    entry = raw["candidates"]["douyinhao88"]
    assert entry["status"] == "pending"  # not changed without --write-config
    assert entry["llm_verdict"]["verdict"] == "llm_approved_high"


def test_write_config_promotes_high_to_approved_and_appends_groups(tmp_path, monkeypatch):
    cands = tmp_path / "discovered_groups.yaml"
    _seed_candidates(cands)
    cfg = _seed_config(tmp_path, cands)
    _seed_raw_message(tmp_path)
    monkeypatch.setattr("tg_intel_crawler.main.CONFIG_PATH", cfg)

    fake_client = _make_mock_llm(stage1_advance=True, stage2_approve=True)
    monkeypatch.setattr(
        "tg_intel_crawler.filter.candidate_reviewer.AsyncOpenAI",
        lambda **kw: fake_client,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["candidates", "llm-review", "--write-config"])
    assert result.exit_code == 0, result.output

    raw = yaml.safe_load(cands.read_text(encoding="utf-8"))
    assert raw["candidates"]["douyinhao88"]["status"] == "approved"

    cfg_after = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert "https://t.me/douyinhao88" in cfg_after["groups"]


def test_stage1_reject_does_not_call_stage2(tmp_path, monkeypatch):
    """A candidate Stage 1 rejects must result in 1 LLM call total, not 2."""
    cands = tmp_path / "discovered_groups.yaml"
    _seed_candidates(cands)
    cfg = _seed_config(tmp_path, cands)
    monkeypatch.setattr("tg_intel_crawler.main.CONFIG_PATH", cfg)

    fake_client = _make_mock_llm(stage1_advance=False, stage2_approve=True)
    monkeypatch.setattr(
        "tg_intel_crawler.filter.candidate_reviewer.AsyncOpenAI",
        lambda **kw: fake_client,
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["candidates", "llm-review"])
    assert result.exit_code == 0, result.output
    # Stage 1 has 1 call, Stage 2 should NOT happen because stage1=reject.
    assert fake_client.chat.completions.create.call_count == 1

    raw = yaml.safe_load(cands.read_text(encoding="utf-8"))
    assert raw["candidates"]["douyinhao88"]["llm_verdict"]["verdict"] == "llm_rejected"
    assert raw["candidates"]["douyinhao88"]["llm_verdict"]["stage"] == 1
