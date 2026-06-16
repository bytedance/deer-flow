#!/usr/bin/env python3
"""
run_planning.py — 万能营销规划 CLI 入口（薄壳）

职责仅三件：解析命令行 → 调 planner.plan() → 输出 JSON。
所有业务逻辑都在自包含的 nbev_core 包里。

导入健壮性：把本脚本所在目录加入 sys.path（基于 __file__，与 CWD 无关），
因此 `import nbev_core` 在 DeerFlow 渐进加载、任意工作目录下都成立。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# —— 唯一的路径处理：脚本自身目录，绝不依赖 parents[N] 猜测 ——
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nbev_core.planner import plan  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="万能营销规划（从零新建）")
    p.add_argument("--user-id", "-uid", required=True, help="登录用户ID，用于解析机构信息")
    p.add_argument("--dimensions", "-d", nargs="+", default=None,
                   help="测算维度，可多选：产品 客户 队伍（缺失会返回需澄清）")
    p.add_argument("--target-nbev", "-tv", default=None, help="目标NBEV（万元，缺失会返回需澄清）")
    p.add_argument("--month", "-m", default=None, help="业务月份 YYYY-MM-01，缺省下月1号")
    p.add_argument("--request-id", "-rid", default=None)
    p.add_argument("--session-id", "-sid", default=None)
    p.add_argument("--combination", "-c", nargs="*", default=None)
    p.add_argument("--max-product-activity-rate", type=float, default=None)
    p.add_argument("--max-avg-fyp-range", type=float, default=None)
    p.add_argument("--max-double-gold-diamond-ratio", type=float, default=None)
    p.add_argument("--output", "-o", default=None, help="结果输出文件路径（可选）")
    p.add_argument("--format", "-f", choices=["json", "md"], default="json",
                   help="输出格式：json（默认，含完整data）或 md（美观表格，供直接呈现）")
    return p.parse_args()


def main():
    a = parse_args()
    out = plan(
        user_id=a.user_id,
        dimensions=a.dimensions,
        target_nbev=a.target_nbev,
        month=a.month,
        request_id=a.request_id,
        session_id=a.session_id,
        combination=a.combination,
        max_product_activity_rate=a.max_product_activity_rate,
        max_avg_fyp_range=a.max_avg_fyp_range,
        max_double_gold_diamond_ratio=a.max_double_gold_diamond_ratio,
    )
    if a.format == "md":
        from nbev_core.render import render_results
        text = render_results(out)
    else:
        text = json.dumps(out, ensure_ascii=False, indent=2)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
