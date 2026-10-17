"""端到端演示：模拟一次 Agent 触发审批 → 人工批准 → 放行的完整链路。

    PYTHONPATH=src python3 scripts/demo_flow.py

用假的 GuardrailRequest 驱动引擎（不需要 DeerFlow / langchain / API key），
证明三态审批、指纹复用、授权范围隔离、审计链这几件事真的成立。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deerflow_governance.budget import BudgetLedger  # noqa: E402
from deerflow_governance.contracts import CallContext, Usage  # noqa: E402
from deerflow_governance.engine import ApprovalEngine  # noqa: E402
from deerflow_governance.policy import PolicyEngine  # noqa: E402
from deerflow_governance.pricing import PriceBook, format_cents  # noqa: E402
from deerflow_governance.store import GovernanceStore  # noqa: E402

CFG = ROOT / "governance.example.yaml"


def line(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def show(engine: ApprovalEngine, ctx: CallContext, label: str) -> object:
    d = engine.decide(ctx)
    flag = "放行" if d.allow else "拦截"
    scope = "子Agent" if ctx.is_subagent else "主Agent"
    print(f"\n[{flag}] {scope} → {ctx.tool_name}: {list(ctx.tool_input.values())[:1]}")
    print(f"      规则 {d.verdict.rule_id} / 风险 {d.verdict.risk} / code={d.code}")
    print(f"      给模型的消息: {d.message.splitlines()[0][:88]}")
    return d


def main() -> int:
    import yaml

    data = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    policy = PolicyEngine.from_dict(data["policy"])
    tmp = tempfile.TemporaryDirectory()
    store = GovernanceStore(Path(tmp.name) / "g.db", jsonl_path=Path(tmp.name) / "audit.jsonl")
    engine = ApprovalEngine(policy, store)

    line("场景 1：只读工具直接放行，不打扰任何人")
    show(engine, CallContext("read_file", {"file_path": "backend/app/main.py"}, thread_id="T1", run_id="R1"), "read")

    line("场景 2：破坏性命令直接拒绝，并明确告诉模型不要重试")
    show(engine, CallContext("bash", {"command": "rm -rf /data/prod"}, thread_id="T1", run_id="R1"), "rm")

    line("场景 3：git push 需要人批 —— 模型连续重试 3 次也只开一张单")
    ctx_push = CallContext("bash", {"command": "git push origin main"}, thread_id="T1", run_id="R1")
    first = show(engine, ctx_push, "push")
    for _ in range(2):
        again = engine.decide(ctx_push)
        assert again.ticket.ticket_id == first.ticket.ticket_id
    print(f"      重试 3 次后待审批队列长度 = {len(store.list_tickets(status=None))} 张单（未被刷爆）")

    line("场景 4：人工批准后同一操作放行；但换成 --force 就不放行（exact 授权不外溢）")
    store.decide(first.ticket.ticket_id, approved=True, by="张三", note="已确认目标分支是 feature 分支")
    show(engine, ctx_push, "push-after")
    show(engine, CallContext("bash", {"command": "git push origin --force main"}, thread_id="T1", run_id="R1"), "force")

    line("场景 5：子 Agent 的 shell 更严（同一条 ls，主 Agent 放行、子 Agent 要批）")
    show(engine, CallContext("bash", {"command": "ls -al"}, thread_id="T1", run_id="R1"), "ls-lead")
    sub = show(engine, CallContext("bash", {"command": "ls -al"}, thread_id="T1", run_id="R1", is_subagent=True), "ls-sub")
    store.decide(sub.ticket.ticket_id, approved=True, by="张三", note="本次调研任务放开子 Agent 只读 shell")
    print("      批准后（grant_scope=tool，30 分钟内同工具放行）：")
    show(engine, CallContext("bash", {"command": "cat README.md"}, thread_id="T1", run_id="R1", is_subagent=True), "cat-sub")

    line("场景 6：跨会话不串权 —— 在 T1 批过的 push，在 T2 依然要重新批")
    show(engine, CallContext("bash", {"command": "git push origin main"}, thread_id="T2", run_id="R9"), "push-T2")

    line("审计账本（决策链完整可追溯）")
    print(f"{'时间序':<6}{'类型':<18}{'工具':<12}{'结论':<12}{'规则':<28}裁决人")
    print("-" * 100)
    for i, r in enumerate(reversed(store.audit_tail(limit=40)), start=1):
        who = r["detail"].get("decided_by", "")
        print(f"{i:<6}{r['kind']:<18}{r['tool_name'][:10]:<12}{r['effect'][:10]:<12}{r['rule_id'][:26]:<28}{who}")
    print("\n统计:", store.stats())

    line("预算账本：三层五维 + 两级阈值")
    ledger = BudgetLedger.from_dict(data["budget"])
    prices = PriceBook.from_dict(data.get("prices") or {})
    for i in range(1, 7):
        usage = Usage(
            input_tokens=48_000, output_tokens=6_000, tool_calls=22, delegations=2, wall_ms=210_000,
            cost_cents=prices.cost_cents("deepseek-chat", 48_000, 6_000),
        )
        ledger.record(usage, run_id="R1", thread_id="T1")
        v = ledger.check(run_id="R1", thread_id="T1")
        snap = ledger.snapshot(run_id="R1", thread_id="T1")["run"]
        cost = format_cents(snap["cost_cents"])
        print(f"  第 {i} 轮  tokens={snap['total_tokens']:>7}  调用={snap['tool_calls']:>3}  委派={snap['delegations']:>2}  成本={cost:>10}  →  {v.level.value.upper()}")
        if v.message:
            print(f"           {v.message[:96]}")
        if v.level.value == "stop":
            break

    line("未知模型的成本：记为 unknown，不伪装成 0")
    led2 = BudgetLedger.from_dict({"run": {"cost_cents": 100}})
    led2.record(Usage(input_tokens=2_000_000, cost_cents=prices.cost_cents("our-internal-model", 2_000_000, 0)), run_id="X", thread_id=None)
    c = led2.counter("run", "X")
    print(f"  cost_cents={format_cents(c.cost_cents)}  cost_unknown_tokens={c.cost_unknown_tokens}  判定={led2.check(run_id='X', thread_id=None).level.value}")
    print("  （若把未知成本当 0，换模型那天整套预算体系会静默失效）")

    tmp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
