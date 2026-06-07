#!/usr/bin/env python3
"""threat-intel-analyst CLI — analysis layer over the FEDERATED intel view.

Read-only. Queries one or many independent SQLite intel DBs (registered in
federation.yaml) as a single unioned view, runs deterministic cross-source
aggregates, and (for report) feeds those aggregates to the LLM to write an
analytical Markdown report. Never touches Telegram; never mutates any DB.

Usage:
  python analyze.py --action list-sources
  python analyze.py --action trends [--day-from 2026-06-01] [--source-platform weibo]
  python analyze.py --action top-groups --limit 10
  python analyze.py --action top-entities
  python analyze.py --action keyword-heat
  python analyze.py --action query --risk-level high --limit 20
  python analyze.py --action report --day-from 2026-06-01

Registry: --registry PATH, else env INTEL_FEDERATION_REGISTRY, else the
federation.yaml next to this script.
LLM config + report output dir come from TG_INTEL_CRAWLER_HOME/config/config.yaml
and TG_INTEL_CRAWLER_HOME/output/reports/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analytics  # noqa: E402
from intel_federation import IntelFederation  # noqa: E402


REPORT_SYSTEM_PROMPT = """你是一名资深黑灰产情报分析师，专注字节跳动/抖音/TikTok 相关风险。
下面给你的是从【多个数据源】的情报库聚合出的【真实统计数据】（趋势、重点来源群、风险类型热度、抽取出的实体：账号/联系方式/链接/工具/价格），数据可能来自 Telegram、微博、论坛等不同来源(source_platform/__db 区分)。

请基于这些数据撰写一份**中文情报研判报告**（Markdown），包含：
1. ## 风险概览：总体态势、各数据源贡献、主要风险类型、风险等级分布、时间趋势
2. ## 重点群组：点名 high 风险高发的来源群（注明属于哪个数据源），分析其活跃度与危害
3. ## 实体线索：归纳高频联系方式/账号/工具/价格，指出跨源关联的团伙或产业链线索
4. ## 趋势研判：结合按天数据判断风险上升还是收敛
5. ## 处置建议：可操作的监控/上报/封禁建议

要求：
- **只能基于给定数据**，不得编造数据中没有的群名、账号或数字；引用数字要准确。
- 若有多个数据源，注意做跨源对比与关联分析。
- 有分析、有研判、有洞察，不要简单复述表格。输出纯 Markdown。"""


def _home() -> Path | None:
    env = os.environ.get("TG_INTEL_CRAWLER_HOME")
    if env and Path(env).exists():
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        cand = parent / "tg-intel-crawler"
        if cand.exists():
            return cand
    return None


def _fed(registry: str | None) -> IntelFederation:
    return IntelFederation.from_registry(registry)


def _scope(a) -> dict:
    return {"day_from": a.day_from or None, "day_to": a.day_to or None,
            "source_platform": a.source_platform or None}


def _llm_report(facts: dict) -> str:
    import yaml
    from openai import OpenAI
    home = _home()
    cfg_path = (home / "config" / "config.yaml") if home else Path("config/config.yaml")
    llm = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}).get("llm")
    if not llm:
        raise SystemExit("llm config not found in config.yaml")
    client = OpenAI(api_key=llm["api_key"], base_url=llm["base_url"])
    resp = client.chat.completions.create(
        model=llm["model"],
        messages=[
            {"role": "system", "content": REPORT_SYSTEM_PROMPT},
            {"role": "user", "content":
             "以下是多源情报库聚合出的真实统计数据（JSON）：\n\n"
             + json.dumps(facts, ensure_ascii=False, indent=2)},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Threat-intel analysis (federated)")
    ap.add_argument("--action", required=True,
                    choices=["list-sources", "trends", "top-groups", "top-entities",
                             "keyword-heat", "query", "report"])
    ap.add_argument("--registry", default=None)
    ap.add_argument("--day-from", default="")
    ap.add_argument("--day-to", default="")
    ap.add_argument("--day", default="")
    ap.add_argument("--risk-level", default="")
    ap.add_argument("--source-platform", default="")
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()

    if a.action == "list-sources":
        fed = _fed(a.registry)
        try:
            out = {"ok": True, "action": "list-sources",
                   "databases": fed.databases, "has_data": not fed.is_empty()}
        finally:
            fed.close()
        print(json.dumps(out, ensure_ascii=False, indent=2)); return 0

    fed = _fed(a.registry)
    if fed.is_empty():
        fed.close()
        print(json.dumps({"ok": False, "error":
              "no intel data across registered DBs; check federation.yaml"},
              ensure_ascii=False, indent=2))
        return 1
    try:
        if a.action == "trends":
            out = {"ok": True, "action": "trends", **analytics.trends(fed, **_scope(a))}
        elif a.action == "top-groups":
            out = {"ok": True, "action": "top-groups",
                   "groups": analytics.top_groups(fed, limit=a.limit, **_scope(a))}
        elif a.action == "top-entities":
            out = {"ok": True, "action": "top-entities",
                   "entities": analytics.top_entities(fed, limit=a.limit, **_scope(a))}
        elif a.action == "keyword-heat":
            out = {"ok": True, "action": "keyword-heat",
                   "risk_types": analytics.keyword_heat(fed, limit=a.limit, **_scope(a))}
        elif a.action == "query":
            res = analytics.query_records(fed, day=a.day or None,
                                          risk_level=a.risk_level or None,
                                          source_platform=a.source_platform or None,
                                          limit=a.limit)
            out = {"ok": True, "action": "query", **res}
        elif a.action == "report":
            facts = analytics.gather_all(fed, **_scope(a))
            if facts["trends"]["total"] == 0:
                out = {"ok": False, "error": "no records in scope"}
            else:
                md = _llm_report(facts)
                home = _home()
                out_dir = (home / "output" / "reports") if home else Path("output/reports")
                out_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                tag = facts["scope"].get("source_platform") or "all"
                rp = out_dir / f"intel_report_{tag}_{stamp}.md"
                rp.write_text(md, encoding="utf-8")
                out = {"ok": True, "action": "report", "report_path": str(rp),
                       "scope": facts["scope"], "sources": facts["sources"],
                       "total_records": facts["trends"]["total"], "report_markdown": md}
    finally:
        fed.close()

    if a.action == "report" and out.get("ok"):
        print(out["report_markdown"])
        print(f"\n[saved to {out['report_path']}]")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
