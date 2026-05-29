#!/usr/bin/env python3
"""Generate comprehensive CRM report."""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Generate CRM report")
    parser.add_argument("--outbound-data", help="Outbound data JSON file")
    parser.add_argument("--event-data", help="Service event data JSON file")
    parser.add_argument("--outbound-stats", help="Outbound statistics JSON file")
    parser.add_argument("--event-stats", help="Event statistics JSON file")
    parser.add_argument("--anomalies", help="Anomalies JSON file")
    parser.add_argument("--output", required=True, help="Output Markdown file")
    args = parser.parse_args()

    try:
        lines = ["# 销售易综合分析报告\n"]

        # Outbound summary
        if args.outbound_stats and Path(args.outbound_stats).exists():
            stats = json.loads(Path(args.outbound_stats).read_text(encoding="utf-8"))
            lines.append("## 出库概况\n")
            lines.append(f"- **总记录数**: {stats.get('total_records', 0)}")
            lines.append(f"- **总数量**: {stats.get('total_quantity', 0):.2f}")
            lines.append(f"- **平均数量**: {stats.get('avg_quantity', 0):.2f}")
            lines.append(f"- **最小/最大**: {stats.get('min_quantity', 0):.2f} / {stats.get('max_quantity', 0):.2f}")
            lines.append("")

            by_spec = stats.get("by_spec_model", {})
            if by_spec:
                lines.append("### 按规格型号\n")
                for spec, qty in sorted(by_spec.items(), key=lambda x: x[1], reverse=True)[:10]:
                    lines.append(f"- {spec}: {qty:.2f}")
                lines.append("")

        # Service events summary
        if args.event_stats and Path(args.event_stats).exists():
            stats = json.loads(Path(args.event_stats).read_text(encoding="utf-8"))
            lines.append("## 服务事件概况\n")
            lines.append(f"- **总记录数**: {stats.get('total_records', 0)}")

            by_unit = stats.get("by_unit", {})
            if by_unit:
                lines.append(f"- **涉及机组**: {len(by_unit)} 个")
            lines.append("")

            by_unit_sorted = sorted(by_unit.items(), key=lambda x: x[1], reverse=True)
            if by_unit_sorted:
                lines.append("### 按机组\n")
                for unit, count in by_unit_sorted[:10]:
                    lines.append(f"- {unit}: {count} 次")
                lines.append("")

        # Anomalies
        if args.anomalies and Path(args.anomalies).exists():
            anomaly_data = json.loads(Path(args.anomalies).read_text(encoding="utf-8"))
            anomalies = anomaly_data.get("anomalies", [])
            if anomalies:
                lines.append(f"## 异常告警 ({len(anomalies)} 个)\n")
                for a in anomalies[:10]:
                    severity = a.get("severity", "low")
                    icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
                    lines.append(f"- {icon} **{severity.upper()}**: {a.get('description', '')}")
                lines.append("")

        report_md = "\n".join(lines)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(report_md, encoding="utf-8")

    except Exception as e:
        print(f"Error generating report: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
