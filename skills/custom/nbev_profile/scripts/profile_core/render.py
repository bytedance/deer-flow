"""
render.py — 把画像结果渲染成美观 Markdown（表格已在 interpreters 预渲染，这里负责拼装）
"""

from __future__ import annotations

from . import config


def render_results(out: dict) -> str:
    org = out.get("org", {})
    parts = []
    if org:
        parts.append(
            f"## 万能营销画像 · {org.get('org_name','')}（{org.get('org_id','')}）　"
            f"数据月份：{org.get('month','')}\n"
        )
    for r in out.get("results", []):
        dim = r.get("dimension", "-")
        cn = config.DIMENSION_CN.get(dim, dim)
        status = r.get("status")
        # 顶层错误（dimension='-'，如非法月份/维度）不挂维度标题
        if dim == "-":
            err = r.get("error", {})
            parts.append(f"⚠️ {r.get('summary','')}" + (f"\n\n（{err.get('hint','')}）" if err.get('hint') else ""))
            parts.append("")
            continue
        parts.append(f"### {cn}画像")
        if status == "success":
            parts.append(r.get("summary", ""))
            if r.get("table_md"):
                parts.append("\n" + r["table_md"])
        elif status == "no_data":
            parts.append(f"📭 {r.get('summary','')}（{r.get('error',{}).get('hint','')}）")
        elif status == "needs_clarification":
            parts.append(f"❓ {r.get('error',{}).get('hint','')}")
        else:
            err = r.get("error", {})
            parts.append(f"⚠️ {r.get('summary','')}\n\n（{err.get('hint','')}）")
        parts.append("")
    return "\n".join(parts).strip()
