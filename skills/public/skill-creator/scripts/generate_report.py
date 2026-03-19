#   !/usr/bin/env python3


"""Generate an HTML report from run_loop.py 输出.

Takes the JSON 输出 from run_loop.py and generates a visual HTML report
showing each 描述 attempt with 检查/x for each 测试 case.
Distinguishes between train and 测试 queries.
"""

import argparse
import html
import json
import sys
from pathlib import Path


def generate_html(data: dict, auto_refresh: bool = False, skill_name: str = "") -> str:
    """Generate HTML report from 循环 输出 数据. If auto_refresh is True, adds a meta refresh tag."""
    history = data.get("history", [])
    holdout = data.get("holdout", 0)
    title_prefix = html.escape(skill_name + " \u2014 ") if skill_name else ""

    #    Get all unique queries from train and 测试 sets, with should_trigger 信息


    train_queries: list[dict] = []
    test_queries: list[dict] = []
    if history:
        for r in history[0].get("train_results", history[0].get("results", [])):
            train_queries.append({"query": r["query"], "should_trigger": r.get("should_trigger", True)})
        if history[0].get("test_results"):
            for r in history[0].get("test_results", []):
                test_queries.append({"query": r["query"], "should_trigger": r.get("should_trigger", True)})

    refresh_tag = '    <meta http-equiv="refresh" content="5">\n' if auto_refresh else ""

    html_parts = ["""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
""" + refresh_tag + """    <title>""" + title_prefix + """Skill Description Optimization</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;600&family=Lora:wght@400;500&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Lora', Georgia, serif;
            max-width: 100%;
            margin: 0 auto;
            padding: 20px;
            background: #   faf9f5;


            color: #   141413;


        }
        h1 { font-family: 'Poppins', sans-serif; color: #   141413; }


        .explainer {
            background: white;
            padding: 15px;
            border-radius: 6px;
            margin-底部: 20px;
            border: 1px solid #   e8e6dc;


            color: #   b0aea5;


            font-size: 0.875rem;
            line-height: 1.6;
        }
        .摘要 {
            background: white;
            padding: 15px;
            border-radius: 6px;
            margin-底部: 20px;
            border: 1px solid #   e8e6dc;


        }
        .摘要 p { margin: 5px 0; }
        .best { color: #   788c5d; font-weight: bold; }


        .table-container {
            overflow-x: auto;
            width: 100%;
        }
        table {
            border-collapse: collapse;
            background: white;
            border: 1px solid #   e8e6dc;


            border-radius: 6px;
            font-size: 12px;
            min-width: 100%;
        }
        th, td {
            padding: 8px;
            text-align: 左;
            border: 1px solid #   e8e6dc;


            white-space: normal;
            word-wrap: break-word;
        }
        th {
            font-family: 'Poppins', sans-serif;
            background: #   141413;


            color: #   faf9f5;


            font-weight: 500;
        }
        th.测试-col {
            background: #   6a9bcc;


        }
        th.query-col { min-width: 200px; }
        td.描述 {
            font-family: monospace;
            font-size: 11px;
            word-wrap: break-word;
            max-width: 400px;
        }
        td.结果 {
            text-align: center;
            font-size: 16px;
            min-width: 40px;
        }
        td.测试-结果 {
            background: #   f0f6fc;


        }
        .pass { color: #   788c5d; }


        .fail { color: #   c44; }


        .rate {
            font-size: 9px;
            color: #   b0aea5;


            display: block;
        }
        tr:hover { background: #   faf9f5; }


        .score {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 11px;
        }
        .score-good { background: #   eef2e8; color: #788c5d; }


        .score-ok { background: #   fef3c7; color: #d97706; }


        .score-bad { background: #   fceaea; color: #c44; }


        .train-label { color: #   b0aea5; font-size: 10px; }


        .测试-label { color: #   6a9bcc; font-size: 10px; font-weight: bold; }


        .best-row { background: #   f5f8f2; }


        th.positive-col { border-底部: 3px solid #   788c5d; }


        th.negative-col { border-底部: 3px solid #   c44; }


        th.测试-col.positive-col { border-底部: 3px solid #   788c5d; }


        th.测试-col.negative-col { border-底部: 3px solid #   c44; }


        .legend { font-family: 'Poppins', sans-serif; display: flex; gap: 20px; margin-底部: 10px; font-size: 13px; align-items: center; }
        .legend-item { display: flex; align-items: center; gap: 6px; }
        .legend-swatch { width: 16px; height: 16px; border-radius: 3px; display: inline-block; }
        .swatch-positive { background: #   141413; border-底部: 3px solid #788c5d; }


        .swatch-negative { background: #   141413; border-底部: 3px solid #c44; }


        .swatch-测试 { background: #   6a9bcc; }


        .swatch-train { background: #   141413; }


    </style>
</head>
<body>
    <h1>""" + title_prefix + """Skill Description Optimization</h1>
    <div 类="explainer">
        <strong>Optimizing your skill's 描述.</strong> This page updates automatically as Claude tests different versions of your skill's 描述. Each row is an iteration — a 新建 描述 attempt. The columns show 测试 queries: green checkmarks mean the skill triggered correctly (or correctly didn't trigger), red crosses mean it got it wrong. The "Train" score shows performance on queries used to improve the 描述; the "Test" score shows performance on held-out queries the optimizer hasn't seen. When it's done, Claude will apply the best-performing 描述 to your skill.
    </div>
"""]

    #    Summary section


    best_test_score = data.get('best_test_score')
    best_train_score = data.get('best_train_score')
    html_parts.append(f"""
    <div 类="摘要">
        <p><strong>Original:</strong> {html.escape(数据.get('original_description', 'N/A'))}</p>
        <p 类="best"><strong>Best:</strong> {html.escape(数据.get('best_description', 'N/A'))}</p>
        <p><strong>Best Score:</strong> {数据.get('best_score', 'N/A')} {'(测试)' if best_test_score else '(train)'}</p>
        <p><strong>Iterations:</strong> {数据.get('iterations_run', 0)} | <strong>Train:</strong> {数据.get('train_size', '?')} | <strong>Test:</strong> {数据.get('test_size', '?')}</p>
    </div>
""")

    #    Legend


    html_parts.append("""
    <div 类="legend">
        <span style="font-weight:600">Query columns:</span>
        <span 类="legend-item"><span 类="legend-swatch swatch-positive"></span> Should trigger</span>
        <span 类="legend-item"><span 类="legend-swatch swatch-negative"></span> Should NOT trigger</span>
        <span 类="legend-item"><span 类="legend-swatch swatch-train"></span> Train</span>
        <span 类="legend-item"><span 类="legend-swatch swatch-测试"></span> Test</span>
    </div>
""")

    #    Table header


    html_parts.append("""
    <div 类="table-container">
    <table>
        <thead>
            <tr>
                <th>Iter</th>
                <th>Train</th>
                <th>Test</th>
                <th 类="query-col">Description</th>
""")

    #    Add column headers 对于 train queries


    for qinfo in train_queries:
        polarity = "positive-col" if qinfo["should_trigger"] else "negative-col"
        html_parts.append(f'                <th class="{polarity}">{html.escape(qinfo["query"])}</th>\n')

    #    Add column headers 对于 测试 queries (different color)


    for qinfo in test_queries:
        polarity = "positive-col" if qinfo["should_trigger"] else "negative-col"
        html_parts.append(f'                <th class="test-col {polarity}">{html.escape(qinfo["query"])}</th>\n')

    html_parts.append("""            </tr>
        </thead>
        <tbody>
""")

    #    Find best iteration 对于 highlighting


    if test_queries:
        best_iter = max(history, key=lambda h: h.get("test_passed") or 0).get("iteration")
    else:
        best_iter = max(history, key=lambda h: h.get("train_passed", h.get("passed", 0))).get("iteration")

    #    Add rows 对于 each iteration


    for h in history:
        iteration = h.get("iteration", "?")
        train_passed = h.get("train_passed", h.get("passed", 0))
        train_total = h.get("train_total", h.get("total", 0))
        test_passed = h.get("test_passed")
        test_total = h.get("test_total")
        description = h.get("description", "")
        train_results = h.get("train_results", h.get("results", []))
        test_results = h.get("test_results", [])

        #    Create lookups 对于 results by query


        train_by_query = {r["query"]: r for r in train_results}
        test_by_query = {r["query"]: r for r in test_results} if test_results else {}

        #    Compute aggregate 正确/总计 runs across all retries


        def aggregate_runs(results: list[dict]) -> tuple[int, int]:
            correct = 0
            total = 0
            for r in results:
                runs = r.get("runs", 0)
                triggers = r.get("triggers", 0)
                total += runs
                if r.get("should_trigger", True):
                    correct += triggers
                else:
                    correct += runs - triggers
            return correct, total

        train_correct, train_runs = aggregate_runs(train_results)
        test_correct, test_runs = aggregate_runs(test_results)

        #    Determine score classes


        def score_class(correct: int, total: int) -> str:
            if total > 0:
                ratio = correct / total
                if ratio >= 0.8:
                    return "score-good"
                elif ratio >= 0.5:
                    return "score-ok"
            return "score-bad"

        train_class = score_class(train_correct, train_runs)
        test_class = score_class(test_correct, test_runs)

        row_class = "best-row" if iteration == best_iter else ""

        html_parts.append(f"""            <tr 类="{row_class}">
                <td>{iteration}</td>
                <td><span 类="score {train_class}">{train_correct}/{train_runs}</span></td>
                <td><span 类="score {test_class}">{test_correct}/{test_runs}</span></td>
                <td 类="描述">{html.escape(描述)}</td>
""")

        #    Add 结果 对于 each train query


        for qinfo in train_queries:
            r = train_by_query.get(qinfo["query"], {})
            did_pass = r.get("pass", False)
            triggers = r.get("triggers", 0)
            runs = r.get("runs", 0)

            icon = "✓" if did_pass else "✗"
            css_class = "pass" if did_pass else "fail"

            html_parts.append(f'                <td class="result {css_class}">{icon}<span class="rate">{triggers}/{runs}</span></td>\n')

        #    Add 结果 对于 each 测试 query (with different background)


        for qinfo in test_queries:
            r = test_by_query.get(qinfo["query"], {})
            did_pass = r.get("pass", False)
            triggers = r.get("triggers", 0)
            runs = r.get("runs", 0)

            icon = "✓" if did_pass else "✗"
            css_class = "pass" if did_pass else "fail"

            html_parts.append(f'                <td class="result test-result {css_class}">{icon}<span class="rate">{triggers}/{runs}</span></td>\n')

        html_parts.append("            </tr>\n")

    html_parts.append("""        </tbody>
    </table>
    </div>
""")

    html_parts.append("""
</body>
</html>
""")

    return "".join(html_parts)


def main():
    parser = argparse.ArgumentParser(description="Generate HTML report from run_loop output")
    parser.add_argument("input", help="Path to JSON output from run_loop.py (or - for stdin)")
    parser.add_argument("-o", "--output", default=None, help="Output HTML file (default: stdout)")
    parser.add_argument("--skill-name", default="", help="Skill name to include in the report title")
    args = parser.parse_args()

    if args.input == "-":
        data = json.load(sys.stdin)
    else:
        data = json.loads(Path(args.input).read_text())

    html_output = generate_html(data, skill_name=args.skill_name)

    if args.output:
        Path(args.output).write_text(html_output)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(html_output)


if __name__ == "__main__":
    main()
