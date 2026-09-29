"""Opt-in live smoke test: classify a small synthetic list through the real plugin path.

Calls the configured backend for real and costs money; nothing here is a benchmark.
Credentials are read only from the named environment variable and never printed.
Run from ``backend/`` in a deployment checkout:

    export TYPESAFE_API_KEY='your-deployment-secret'
    uv run python ../examples/deerflow-extension-jev-classify/scripts/verify_live.py

For a chat backend add ``--backend llm --llm-url ... --llm-model ... --api-key-env NAME``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deerflow_extension_api.auth import ExtensionPrincipal  # noqa: E402
from deerflow_extension_api.plugins import ToolContext  # noqa: E402

from deerflow.extensions.loader import ExtensionSpec, load_extensions  # noqa: E402

CATEGORIES = [
    {"name": "billing", "description": "Payments, invoices, refunds and subscription charges."},
    {"name": "technical", "description": "Errors, crashes, integration or API failures."},
    {"name": "account", "description": "Login, password, profile and permission requests."},
    {"name": "other", "description": "Anything that fits none of the other categories."},
]
# Synthetic sentences with an obvious label; a disagreement is worth a look, not a failure.
ITEMS = [
    ("en-1", "I was charged twice for last month's subscription.", "billing"),
    ("en-2", "The webhook endpoint returns HTTP 500 since yesterday.", "technical"),
    ("en-3", "How do I reset my password?", "account"),
    ("en-4", "Please send me the invoice for order 4471.", "billing"),
    ("en-5", "The app crashes when I open the settings page.", "technical"),
    ("en-6", "Can you add my colleague as an admin on our workspace?", "account"),
    ("en-7", "What are your office hours?", "other"),
    ("en-8", "Refund request: the product never arrived.", "billing"),
    ("en-9", "The API key I generated does not work with the SDK.", "technical"),
    ("en-10", "I want to change the email address on my profile.", "account"),
    ("zh-1", "上个月的订阅费被扣了两次。", "billing"),
    ("zh-2", "从昨天开始 webhook 接口一直返回 500。", "technical"),
    ("zh-3", "怎么重置密码？", "account"),
    ("zh-4", "请把订单 4471 的发票发给我。", "billing"),
    ("zh-5", "打开设置页面应用就崩溃。", "technical"),
    ("zh-6", "能把我同事加为工作区管理员吗？", "account"),
    ("zh-7", "你们的营业时间是几点？", "other"),
    ("zh-8", "申请退款：商品一直没有收到。", "billing"),
    ("zh-9", "我生成的 API key 在 SDK 里用不了。", "technical"),
    ("zh-10", "我想修改个人资料里的邮箱。", "account"),
    ("blank", "   ", None),
    ("long", "x" * 2001, None),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--backend", choices=["jev", "llm"], default="jev")
    parser.add_argument("--api-key-env", default=None, help="environment variable holding the key (default: the plugin's default for the backend)")
    parser.add_argument("--model", default=None, help="Jev model name (default jev-latest)")
    parser.add_argument("--llm-url", default=None)
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()

    config: dict[str, object] = {"enabled": True, "backend": args.backend, "batch_size": args.batch_size}
    if args.backend == "jev":
        if args.model:
            config["jev_model"] = args.model
        if args.api_key_env:
            config["jev_api_key_env"] = args.api_key_env
    else:
        config.update({"llm_url": args.llm_url, "llm_model": args.llm_model})
        if args.api_key_env:
            config["llm_api_key_env"] = args.api_key_env
    key_env = str(config.get("jev_api_key_env" if args.backend == "jev" else "llm_api_key_env", "TYPESAFE_API_KEY" if args.backend == "jev" else "CLASSIFY_LLM_API_KEY"))
    if not os.environ.get(key_env):
        print(f"no credential in environment variable {key_env}", file=sys.stderr)
        return 2

    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_jev_classify:install", config=config)])
    if diagnostics or not loaded.plugins:
        print(f"extension did not load: {[str(d) for d in diagnostics]}", file=sys.stderr)
        return 2
    ((_, plugin),) = loaded.plugins
    (tool,) = plugin.tools
    payload = {"items": [{"id": identifier, "text": text} for identifier, text, _ in ITEMS], "categories": CATEGORIES}
    started = time.perf_counter()
    result = asyncio.run(tool.handler(payload, ToolContext(ExtensionPrincipal("smoke"), {"enabled": True}, None)))
    elapsed = time.perf_counter() - started
    if "error" in result:
        print(json.dumps(result, ensure_ascii=False))
        return 1
    expected = {identifier: label for identifier, _, label in ITEMS}
    agree = sum(1 for entry in result["results"] if entry["status"] == "ok" and entry["label"] == expected[entry["id"]])
    for entry in result["results"]:
        flag = "" if entry["label"] == expected[entry["id"]] or entry["status"] != "ok" else "  <- expected " + str(expected[entry["id"]])
        print(f"{entry['id']:>6}  {entry['status']:<13} {entry['error']:<16} {entry['label'] or '-'}{flag}")
    print(
        json.dumps(
            {"backend": result["backend"], "model": result["model"], "counts": result["counts"], "requests": result["requests"], "agreement": f"{agree}/{sum(1 for e in expected.values() if e)}", "elapsed_s": round(elapsed, 2)},
            ensure_ascii=False,
        )
    )
    return 0 if result["requests"] else 1


if __name__ == "__main__":
    sys.exit(main())
