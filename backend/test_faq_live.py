"""Live FAQ MCP test — call faq_search tool through MCP server module directly.

Imports the faq_server module and invokes the registered tool function,
which is equivalent to calling through the MCP protocol (same code path).
Results are written to faq_live_test_results.json.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "packages", "harness"))

os.environ["RAGFLOW_BASE_URL"] = "http://localhost:9380"
os.environ.setdefault("RAGFLOW_API_KEY", "")
os.environ["FAQ_DATASET_IDS"] = "ec218bae4dd611f198d46d41961130d5"

if not os.environ["RAGFLOW_API_KEY"]:
    raise RuntimeError("RAGFLOW_API_KEY is required for this live test")

# Block deerflow.mcp package __init__ (requires langchain_core not available in bare Python)
import importlib
import types
_mcp_mock = types.ModuleType("deerflow.mcp")
_mcp_mock.__path__ = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "packages", "harness", "deerflow", "mcp")]
_mcp_mock.__package__ = "deerflow.mcp"
sys.modules["deerflow.mcp"] = _mcp_mock

from deerflow.mcp.faq_server import faq_search

QUESTIONS = [
    {
        "label": "高相关（原知识库问题）",
        "question": "300works 的 Manual、Auto 1、Auto 2、Auto 3 自动化模式有什么区别？现场排查自动化卡点时应该怎么判断问题在哪一段？",
    },
    {
        "label": "中相关（部分匹配）",
        "question": "300works 自动化模式 Auto 1 和 Auto 2 有什么不同？",
    },
    {
        "label": "低相关（不同主题）",
        "question": "300works 系统怎么安装部署？",
    },
]


def main():
    results = []

    for q_info in QUESTIONS:
        input_data = {
            "label": q_info["label"],
            "question": q_info["question"],
            "tool": "faq_search",
            "top_k": 3,
        }
        print(f"Testing: [{q_info['label']}] {q_info['question']}")
        start = time.monotonic()

        raw_json = faq_search(question=q_info["question"], top_k=3)
        elapsed = (time.monotonic() - start) * 1000

        output_data = json.loads(raw_json)

        entry = {
            "input": input_data,
            "output": output_data,
            "elapsed_ms": round(elapsed, 1),
        }
        results.append(entry)

        best_score = output_data.get("best_faq", {}).get("score", "N/A") if output_data.get("best_faq") else "N/A"
        matches = len(output_data.get("all_matches", []))
        print(f"  -> best_score={best_score}, matches={matches}, time={elapsed:.0f}ms")

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "faq_live_test_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
