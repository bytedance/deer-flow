from ai_report.render_markdown_v2 import render_markdown


def test_render_markdown_from_payload():
    payload = {
        "report": {"report_id": "business_analysis", "report_title": "2024年经营分析报告"},
        "sections": [{
            "section_id": "overview",
            "section_title": "一、总体经营情况",
            "section_order": 10,
            "tables": [{
                "table_id": "main_metrics",
                "table_title": "主要经营指标表",
                "table_order": 10,
                "headers": [],
                "rows": [{
                    "branch_num": "27020199",
                    "branch_short_name": "王益联社",
                    "cells": {"BAS_0263@本期": "1000", "贷款同比增速": "0.1"},
                    "cell_status": {"BAS_0263@本期": "ok", "贷款同比增速": "ok"},
                }],
                "description_text": "贷款余额同比增长。",
            }],
        }],
    }

    md = render_markdown(payload)

    assert "# 2024年经营分析报告" in md
    assert "## 一、总体经营情况" in md
    assert "### 主要经营指标表" in md
    assert "贷款余额同比增长。" in md
    assert "| branch_num | branch_short_name | BAS_0263@本期 | 贷款同比增速 |" in md
    assert "| 27020199 | 王益联社 | 1000 | 0.1 |" in md
