#!/usr/bin/env python3
"""
run_profile.py — 万能营销画像 CLI 入口（薄壳）

职责：解析命令行 → 调 profiler.profile() → 输出（json 或 md）。
导入健壮性：把脚本自身目录加入 sys.path（基于 __file__，与 CWD 无关）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profile_core.profiler import profile  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="万能营销画像查询")
    p.add_argument("--user-id", "-uid", required=True, help="登录用户ID，用于解析机构（branch_code=org_id）")
    p.add_argument("--dimensions", "-d", nargs="+", default=None,
                   help="画像维度：队伍 客户 产品 全部；缺省=全部三维")
    p.add_argument("--month", "-m", default=None, help="数据月份 YYYY-MM-01，缺省=上个月1号")
    p.add_argument("--request-id", "-rid", default=None)
    p.add_argument("--format", "-f", choices=["json", "md"], default="json",
                   help="输出格式：json（默认）或 md（美观表格，供直接呈现）")
    p.add_argument("--output", "-o", default=None, help="结果输出文件路径（可选）")
    return p.parse_args()


def main():
    a = parse_args()
    out = profile(
        user_id=a.user_id,
        dimensions=a.dimensions,
        month=a.month,
        request_id=a.request_id,
    )
    if a.format == "md":
        from profile_core.render import render_results
        text = render_results(out)
    else:
        text = json.dumps(out, ensure_ascii=False, indent=2)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
