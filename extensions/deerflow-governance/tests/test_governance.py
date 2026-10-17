"""治理插件核心层单测 —— 全部可离线运行，不需要 DeerFlow / langchain / API key。

    python3 -m unittest discover -s tests -v
    pytest tests -q                              # 装了 pytest 也能跑

覆盖的是本包真正的风险面：策略求值、指纹稳定性、审批状态机、预算熔断、审计不可篡改。
适配层（provider.py / middleware.py）需要 DeerFlow 环境，验收方式见 docs/INTEGRATION.md。
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from deerflow_governance.budget import BudgetLedger, Limits  # noqa: E402
from deerflow_governance.cli import build_parser  # noqa: E402
from deerflow_governance.contracts import BudgetLevel, CallContext, Effect, TicketStatus, Usage  # noqa: E402
from deerflow_governance.engine import ApprovalEngine  # noqa: E402
from deerflow_governance.fingerprint import brief, compute  # noqa: E402
from deerflow_governance.policy import PolicyEngine  # noqa: E402
from deerflow_governance.pricing import PriceBook, format_cents  # noqa: E402
from deerflow_governance.store import GovernanceStore  # noqa: E402

POLICY = {
    "default_effect": "allow",
    "rules": [
        {"id": "readonly", "tools": ["read_file", "ls", "grep"], "effect": "allow", "risk": "low", "reason": "只读"},
        {
            "id": "bash-destructive", "tools": ["bash"], "effect": "deny", "risk": "critical", "reason": "破坏性命令",
            "when_any": [{"arg": "command", "regex": r"rm\s+(-[a-zA-Z]*\s+)*-?[rf]"}, {"arg": "command", "regex": r"\bmkfs\b"}],
        },
        {
            "id": "bash-push", "tools": ["bash"], "effect": "ask", "risk": "high", "reason": "涉及远程推送",
            "when_any": [{"arg": "command", "regex": r"git\s+push"}], "grant_scope": "exact",
        },
        {
            "id": "subagent-bash", "tools": ["bash"], "scope": "subagent", "effect": "ask", "risk": "high",
            "reason": "子 Agent 执行 shell", "grant_scope": "tool", "ttl_seconds": 60,
        },
        {"id": "bash-default", "tools": ["bash"], "effect": "allow", "risk": "medium", "reason": "常规 shell"},
        {
            "id": "write-protected", "tools": ["write_file"], "effect": "ask", "risk": "high", "reason": "受保护路径",
            "when": [{"arg": "file_path", "regex": r"(^|/)\.env"}],
        },
        {"id": "mcp", "tools": ["mcp__*"], "effect": "ask", "risk": "high", "reason": "外部服务", "grant_scope": "tool"},
        {"id": "admin-only", "tools": ["update_agent"], "effect": "allow", "risk": "high", "reason": "管理员放行", "roles": ["admin"]},
    ],
}


def ctx(tool: str, **args) -> CallContext:
    sub = args.pop("_subagent", False)
    thread = args.pop("_thread", "t1")
    role = args.pop("_role", None)
    return CallContext(tool_name=tool, tool_input=args, thread_id=thread, run_id="r1", is_subagent=sub, user_role=role)


class TestCLI(unittest.TestCase):
    def test_config_works_before_or_after_subcommand(self):
        parser = build_parser()

        before = parser.parse_args(["--config", "gov.yaml", "validate"])
        after = parser.parse_args(["validate", "--config", "gov.yaml"])

        self.assertEqual(before.command, "validate")
        self.assertEqual(before.config, "gov.yaml")
        self.assertEqual(after.command, "validate")
        self.assertEqual(after.config, "gov.yaml")

    def test_config_after_subcommand_with_arguments(self):
        args = build_parser().parse_args(["simulate", "--config", "gov.yaml", "--tool", "bash", "--arg", "command=git push"])

        self.assertEqual(args.command, "simulate")
        self.assertEqual(args.config, "gov.yaml")
        self.assertEqual(args.tool, "bash")
        self.assertEqual(args.arg, ["command=git push"])


class TestPolicy(unittest.TestCase):
    def setUp(self):
        self.engine = PolicyEngine.from_dict(POLICY)

    def test_first_match_wins(self):
        """bash-destructive 排在 bash-default 前面，顺序必须决定结果。"""
        v = self.engine.evaluate(ctx("bash", command="rm -rf build/"))
        self.assertIs(v.effect, Effect.DENY)
        self.assertEqual(v.rule_id, "bash-destructive")

    def test_same_tool_different_risk(self):
        """同一个工具按参数分流 —— 这是「只按工具名做策略」办不到的。"""
        self.assertIs(self.engine.evaluate(ctx("bash", command="pytest -q")).effect, Effect.ALLOW)
        self.assertIs(self.engine.evaluate(ctx("bash", command="git push origin main")).effect, Effect.ASK)
        self.assertIs(self.engine.evaluate(ctx("bash", command="mkfs.ext4 /dev/sda")).effect, Effect.DENY)

    def test_scope_subagent_is_stricter(self):
        self.assertIs(self.engine.evaluate(ctx("bash", command="ls -al")).effect, Effect.ALLOW)
        self.assertIs(self.engine.evaluate(ctx("bash", command="ls -al", _subagent=True)).effect, Effect.ASK)

    def test_glob_tool_match(self):
        self.assertEqual(self.engine.evaluate(ctx("mcp__github__create_issue")).rule_id, "mcp")

    def test_arg_condition_and_semantics(self):
        self.assertIs(self.engine.evaluate(ctx("write_file", file_path="app/.env")).effect, Effect.ASK)
        self.assertIs(self.engine.evaluate(ctx("write_file", file_path="app/main.py")).effect, Effect.ALLOW)

    def test_role_gate(self):
        self.assertEqual(self.engine.evaluate(ctx("update_agent", _role="admin")).rule_id, "admin-only")
        self.assertEqual(self.engine.evaluate(ctx("update_agent", _role="viewer")).rule_id, "__default__")

    def test_default_effect_must_be_explicit(self):
        with self.assertRaises(ValueError):
            PolicyEngine.from_dict({"rules": []})

    def test_duplicate_rule_id_rejected(self):
        with self.assertRaises(ValueError):
            PolicyEngine.from_dict({"default_effect": "allow", "rules": [
                {"id": "x", "effect": "allow"}, {"id": "x", "effect": "deny"},
            ]})

    def test_unknown_field_rejected(self):
        """配置写错字段名必须报错。静默忽略拼错的规则字段 = 策略静默失效。"""
        with self.assertRaises(ValueError):
            PolicyEngine.from_dict({"default_effect": "allow", "rules": [{"id": "x", "effect": "ask", "whn": []}]})

    def test_explain(self):
        hits = dict(self.engine.explain(ctx("bash", command="rm -rf /")))
        self.assertTrue(hits["bash-destructive"])
        self.assertFalse(hits["readonly"])


class TestFingerprint(unittest.TestCase):
    def test_stable_across_key_order_and_whitespace(self):
        a = compute(tool_name="bash", tool_input={"command": "pytest  -q", "cwd": "."}, rule_id="r", thread_id="t")
        b = compute(tool_name="bash", tool_input={"cwd": ".", "command": "pytest -q"}, rule_id="r", thread_id="t")
        self.assertEqual(a, b)

    def test_volatile_keys_excluded(self):
        a = compute(tool_name="bash", tool_input={"command": "ls", "tool_call_id": "1"}, rule_id="r", thread_id="t")
        b = compute(tool_name="bash", tool_input={"command": "ls", "tool_call_id": "2"}, rule_id="r", thread_id="t")
        self.assertEqual(a, b)

    def test_scope_widens_coverage(self):
        kw = dict(tool_name="bash", rule_id="r", thread_id="t")
        exact_a = compute(tool_input={"command": "ls"}, scope="exact", **kw)
        exact_b = compute(tool_input={"command": "pwd"}, scope="exact", **kw)
        tool_a = compute(tool_input={"command": "ls"}, scope="tool", **kw)
        tool_b = compute(tool_input={"command": "pwd"}, scope="tool", **kw)
        self.assertNotEqual(exact_a, exact_b)
        self.assertEqual(tool_a, tool_b)

    def test_thread_bound(self):
        kw = dict(tool_name="bash", tool_input={"command": "ls"}, rule_id="r")
        self.assertNotEqual(compute(thread_id="a", **kw), compute(thread_id="b", **kw))
        self.assertEqual(compute(thread_id="a", thread_bound=False, **kw), compute(thread_id="b", thread_bound=False, **kw))

    def test_brief_prefers_command(self):
        self.assertIn("git push", brief("bash", {"command": "git push origin main", "cwd": "/x"}))

    def test_invalid_scope(self):
        with self.assertRaises(ValueError):
            compute(tool_name="bash", tool_input={}, rule_id="r", scope="whatever")


class GovernanceTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = GovernanceStore(Path(self.tmp.name) / "g.db", jsonl_path=Path(self.tmp.name) / "audit.jsonl")
        self.engine = ApprovalEngine(PolicyEngine.from_dict(POLICY), self.store)

    def tearDown(self):
        self.tmp.cleanup()


class TestApprovalFlow(GovernanceTestBase):
    def test_allow_passes_through(self):
        d = self.engine.decide(ctx("read_file", file_path="a.py"))
        self.assertTrue(d.allow)
        self.assertIsNone(d.ticket)

    def test_deny_tells_model_not_to_retry(self):
        d = self.engine.decide(ctx("bash", command="rm -rf /"))
        self.assertFalse(d.allow)
        self.assertEqual(d.code, "governance.denied")
        self.assertIn("不要重试", d.message)
        self.assertIsNone(d.ticket)

    def test_ask_opens_ticket_and_blocks(self):
        d = self.engine.decide(ctx("bash", command="git push origin main"))
        self.assertFalse(d.allow)
        self.assertEqual(d.code, "governance.approval_pending")
        self.assertIsNotNone(d.ticket)
        self.assertIn(d.ticket.ticket_id, d.message)
        self.assertIn("不要重试", d.message)  # 防止模型换工具绕过

    def test_retry_reuses_pending_ticket(self):
        """模型重试不能刷爆审批队列 —— 同一指纹只应有一张 pending 单。"""
        c = ctx("bash", command="git push origin main")
        first = self.engine.decide(c)
        for _ in range(4):
            again = self.engine.decide(c)
            self.assertEqual(again.ticket.ticket_id, first.ticket.ticket_id)
        self.assertEqual(len(self.store.list_tickets(status=TicketStatus.PENDING)), 1)

    def test_approved_then_allowed(self):
        c = ctx("bash", command="git push origin main")
        pending = self.engine.decide(c)
        self.store.decide(pending.ticket.ticket_id, approved=True, by="张三", note="确认过分支")
        after = self.engine.decide(c)
        self.assertTrue(after.allow)
        self.assertIn("张三", after.message)

    def test_denied_ticket_keeps_blocking(self):
        c = ctx("bash", command="git push origin main")
        pending = self.engine.decide(c)
        self.store.decide(pending.ticket.ticket_id, approved=False, by="李四", note="禁止直推主干")
        after = self.engine.decide(c)
        self.assertFalse(after.allow)
        self.assertEqual(after.code, "governance.approval_denied")
        self.assertIn("禁止直推主干", after.message)

    def test_double_decision_rejected(self):
        pending = self.engine.decide(ctx("bash", command="git push origin main"))
        self.assertIsNotNone(self.store.decide(pending.ticket.ticket_id, approved=True, by="a"))
        self.assertIsNone(self.store.decide(pending.ticket.ticket_id, approved=False, by="b"))

    def test_tool_scope_grant_covers_similar_calls(self):
        """子 Agent 规则用 grant_scope=tool：批一次 bash，同工具其他命令也放行。"""
        first = self.engine.decide(ctx("bash", command="ls", _subagent=True))
        self.store.decide(first.ticket.ticket_id, approved=True, by="张三")
        second = self.engine.decide(ctx("bash", command="cat README.md", _subagent=True))
        self.assertTrue(second.allow)

    def test_exact_scope_does_not_leak(self):
        """而 exact 授权不能外溢到别的命令 —— 这是审批粒度的核心保证。"""
        first = self.engine.decide(ctx("bash", command="git push origin main"))
        self.store.decide(first.ticket.ticket_id, approved=True, by="张三")
        other = self.engine.decide(ctx("bash", command="git push origin --force main"))
        self.assertFalse(other.allow)

    def test_grant_expires(self):
        c = ctx("bash", command="ls", _subagent=True)  # 该规则 ttl_seconds=60
        first = self.engine.decide(c, now=1000.0)
        self.store.decide(first.ticket.ticket_id, approved=True, by="张三", now=1001.0)
        self.assertTrue(self.engine.decide(c, now=1030.0).allow)
        expired = self.engine.decide(c, now=2000.0)
        self.assertFalse(expired.allow)
        self.assertEqual(expired.code, "governance.approval_expired")

    def test_grant_is_thread_bound(self):
        approved = self.engine.decide(ctx("bash", command="git push origin main", _thread="A"))
        self.store.decide(approved.ticket.ticket_id, approved=True, by="张三")
        self.assertFalse(self.engine.decide(ctx("bash", command="git push origin main", _thread="B")).allow)

    def test_invalid_mode(self):
        with self.assertRaises(ValueError):
            ApprovalEngine(PolicyEngine.from_dict(POLICY), self.store, mode="magic")


class TestAudit(GovernanceTestBase):
    def test_every_decision_is_audited(self):
        self.engine.decide(ctx("read_file", file_path="a.py"))
        self.engine.decide(ctx("bash", command="rm -rf /"))
        d = self.engine.decide(ctx("bash", command="git push origin main"))
        self.store.decide(d.ticket.ticket_id, approved=True, by="张三", note="ok")

        kinds = [r["kind"] for r in self.store.audit_tail(limit=50)]
        self.assertEqual(kinds.count("policy_decision"), 3)
        self.assertEqual(kinds.count("ticket_created"), 1)
        self.assertEqual(kinds.count("ticket_decided"), 1)

    def test_audit_is_append_only(self):
        """审计表不提供任何 update/delete 接口 —— 能改的审计没有审计价值。"""
        public = {n for n in dir(self.store) if not n.startswith("_")}
        self.assertFalse({"update_audit", "delete_audit", "clear_audit"} & public)

    def test_jsonl_mirror(self):
        self.engine.decide(ctx("read_file", file_path="a.py"))
        lines = self.store.jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(lines), 1)

    def test_stats_return_none_not_zero_when_empty(self):
        s = self.store.stats()
        self.assertEqual(s["decisions"], 0)
        self.assertIsNone(s["approval_rate"])


class TestBudget(unittest.TestCase):
    def ledger(self, **over):
        cfg = {"run": {"total_tokens": 1000, "tool_calls": 10, "warn_ratio": 0.8}, "thread": {"total_tokens": 3000}}
        cfg.update(over)
        return BudgetLedger.from_dict(cfg)

    def test_ok_then_warn_then_stop(self):
        led = self.ledger()
        led.record(Usage(input_tokens=400, output_tokens=100), run_id="r", thread_id="t")
        self.assertIs(led.check(run_id="r", thread_id="t").level, BudgetLevel.OK)
        led.record(Usage(input_tokens=350), run_id="r", thread_id="t")
        self.assertIs(led.check(run_id="r", thread_id="t").level, BudgetLevel.WARN)
        led.record(Usage(input_tokens=300), run_id="r", thread_id="t")
        v = led.check(run_id="r", thread_id="t")
        self.assertIs(v.level, BudgetLevel.STOP)
        self.assertEqual(v.dimension, "total_tokens")
        self.assertIn("熔断", v.message)

    def test_stop_beats_warn_across_dimensions(self):
        led = self.ledger()
        led.record(Usage(input_tokens=850), run_id="r", thread_id="t")  # warn
        led.record(Usage(tool_calls=10), run_id="r", thread_id="t")  # stop
        v = led.check(run_id="r", thread_id="t")
        self.assertIs(v.level, BudgetLevel.STOP)
        self.assertEqual(v.dimension, "tool_calls")

    def test_thread_layer_catches_what_run_layer_misses(self):
        """单 run 都不超标，但一个会话里连开多个 run 会超 —— 这正是分层的意义。"""
        led = self.ledger()
        for i in range(4):
            led.record(Usage(input_tokens=900), run_id=f"r{i}", thread_id="t")
            self.assertIsNot(led.check(run_id=f"r{i}", thread_id="t").level, BudgetLevel.STOP if i < 3 else BudgetLevel.OK)
        self.assertIs(led.check(run_id="r9", thread_id="t").level, BudgetLevel.STOP)

    def test_unknown_cost_not_counted_as_zero(self):
        led = BudgetLedger.from_dict({"run": {"cost_cents": 100}})
        led.record(Usage(input_tokens=999999, cost_cents=None), run_id="r", thread_id=None)
        counter = led.counter("run", "r")
        self.assertEqual(counter.cost_cents, 0.0)
        self.assertEqual(counter.cost_unknown_tokens, 999999)  # 单独统计，不伪装成 0 成本
        self.assertIs(led.check(run_id="r", thread_id=None).level, BudgetLevel.OK)

    def test_unlimited_dimension_never_triggers(self):
        led = BudgetLedger.from_dict({"run": {"total_tokens": 100}})
        led.record(Usage(tool_calls=10_000), run_id="r", thread_id=None)
        self.assertIs(led.check(run_id="r", thread_id=None).level, BudgetLevel.OK)

    def test_unknown_level_and_dimension_rejected(self):
        with self.assertRaises(ValueError):
            BudgetLedger.from_dict({"forever": {"total_tokens": 1}})
        with self.assertRaises(ValueError):
            Limits.from_dict({"tokens": 1})

    def test_counter_is_bounded(self):
        led = BudgetLedger.from_dict({"run": {"total_tokens": 10}}, maxsize=5)
        for i in range(20):
            led.record(Usage(input_tokens=1), run_id=f"r{i}", thread_id=None)
        self.assertLessEqual(len(led._counters["run"]), 5)

    def test_snapshot_shape(self):
        led = self.ledger()
        led.record(Usage(input_tokens=10, output_tokens=5, tool_calls=1, delegations=1), run_id="r", thread_id="t")
        snap = led.snapshot(run_id="r", thread_id="t")
        self.assertEqual(snap["run"]["total_tokens"], 15)
        self.assertEqual(snap["run"]["delegations"], 1)


class TestPricing(unittest.TestCase):
    def test_exact_and_glob(self):
        book = PriceBook()
        self.assertIsNotNone(book.lookup("deepseek-chat"))
        self.assertIsNotNone(book.lookup("qwen3-coder-plus"))

    def test_longest_pattern_wins(self):
        book = PriceBook({"qwen*": None, "qwen3-coder*": None} and {
            "qwen*": __import__("deerflow_governance.pricing", fromlist=["Price"]).Price(1, 1),
            "qwen3-coder*": __import__("deerflow_governance.pricing", fromlist=["Price"]).Price(9, 9),
        })
        self.assertEqual(book.lookup("qwen3-coder-plus").input_cents_per_mtok, 9)

    def test_unknown_model_is_none_not_zero(self):
        self.assertIsNone(PriceBook().cost_cents("some-internal-model", 1_000_000, 1_000_000))
        self.assertEqual(format_cents(None), "N/A")

    def test_strict_mode_raises(self):
        with self.assertRaises(KeyError):
            PriceBook(strict=True).lookup("nope-model")

    def test_cost_math(self):
        cents = PriceBook().cost_cents("deepseek-chat", 1_000_000, 1_000_000)
        self.assertAlmostEqual(cents, 1000.0, places=4)  # 200 + 800


if __name__ == "__main__":
    unittest.main()
