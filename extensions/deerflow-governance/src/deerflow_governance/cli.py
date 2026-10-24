"""审批与审计命令行。零三方依赖（argparse + stdlib），可在没装 DeerFlow 的机器上跑。

审批的人通常不是跑 agent 的人，这个 CLI 就是给他们的：

    governance pending                     # 看待审批队列
    governance show APR-XXXX               # 看单据详情
    governance approve APR-XXXX --by 张三 --note "确认过目标目录"
    governance deny    APR-XXXX --by 张三 --note "禁止直接改生产配置"
    governance audit --thread <id> -n 50   # 查审计账本
    governance stats                       # 治理概览（真实数据，没有就显示 N/A）
    governance simulate --tool bash --arg command="rm -rf build"   # 干跑策略，上线前验证规则
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from .config import load as load_config
from .contracts import CallContext, TicketStatus
from .engine import ApprovalEngine
from .policy import PolicyEngine
from .store import GovernanceStore


class _ConfigArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        command_config = getattr(parsed, "config", None)
        global_config = getattr(parsed, "_global_config", None)
        parsed.config = command_config or global_config
        if hasattr(parsed, "_global_config"):
            delattr(parsed, "_global_config")
        return parsed


def _fmt_ts(ts: float | None) -> str:
    return time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "-"


def _store(args) -> GovernanceStore:
    return load_config(args.config).build_store()


def cmd_pending(args) -> int:
    tickets = _store(args).list_tickets(status=TicketStatus.PENDING, limit=args.limit)
    if not tickets:
        print("待审批队列为空")
        return 0
    print(f"{'单号':<16}{'风险':<10}{'范围':<10}{'创建':<14}摘要")
    print("-" * 100)
    for t in tickets:
        scope = "子Agent" if t.is_subagent else "主Agent"
        print(f"{t.ticket_id:<16}{t.risk:<10}{scope:<10}{_fmt_ts(t.created_at):<14}{t.tool_input_brief}")
    return 0


def cmd_show(args) -> int:
    ticket = _store(args).get_ticket(args.ticket_id)
    if ticket is None:
        print(f"找不到审批单 {args.ticket_id}", file=sys.stderr)
        return 1
    for key, value in ticket.__dict__.items():
        if key in {"created_at", "decided_at", "expires_at"}:
            value = _fmt_ts(value)
        if hasattr(value, "value"):
            value = value.value
        print(f"{key:<18}: {value}")
    return 0


def _decide(args, approved: bool) -> int:
    ticket = _store(args).decide(args.ticket_id, approved=approved, by=args.by, note=args.note)
    if ticket is None:
        print(f"{args.ticket_id} 不存在，或已经被裁决过（不允许二次裁决）", file=sys.stderr)
        return 1
    verb = "已批准" if approved else "已驳回"
    expire = f"，有效期至 {_fmt_ts(ticket.expires_at)}" if ticket.expires_at else "（仅本次有效）"
    print(f"{verb} {ticket.ticket_id}{expire if approved else ''}")
    print(f"  操作: {ticket.tool_input_brief}")
    print(f"  裁决人: {args.by}　意见: {args.note or '（无）'}")
    return 0


def cmd_approve(args) -> int:
    return _decide(args, True)


def cmd_deny(args) -> int:
    return _decide(args, False)


def cmd_audit(args) -> int:
    rows = _store(args).audit_tail(limit=args.limit, thread_id=args.thread)
    if not rows:
        print("审计账本为空")
        return 0
    if args.json:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False, default=str))
        return 0
    print(f"{'时间':<14}{'类型':<18}{'工具':<16}{'结论':<22}{'规则':<20}摘要")
    print("-" * 120)
    for r in rows:
        brief = r["detail"].get("brief", "") if isinstance(r.get("detail"), dict) else ""
        print(f"{_fmt_ts(r['ts']):<14}{r['kind']:<18}{r['tool_name'][:14]:<16}{r['effect'][:20]:<22}{r['rule_id'][:18]:<20}{brief[:50]}")
    return 0


def cmd_stats(args) -> int:
    stats = _store(args).stats()
    if stats["decisions"] == 0:
        print("暂无治理记录（N/A）")
        return 0
    for key, value in stats.items():
        print(f"{key:<18}: {value if value is not None else 'N/A'}")
    return 0


def cmd_expire(args) -> int:
    print(f"已将 {_store(args).expire_stale()} 张过期批准置为 expired")
    return 0


def cmd_simulate(args) -> int:
    """干跑：不落库、不开单，只看策略会怎么判。上线新规则前必跑。"""
    cfg = load_config(args.config)
    tool_input = {}
    for pair in args.arg or []:
        if "=" not in pair:
            print(f"参数格式应为 key=value，收到: {pair}", file=sys.stderr)
            return 2
        key, value = pair.split("=", 1)
        tool_input[key] = value

    ctx = CallContext(tool_name=args.tool, tool_input=tool_input, thread_id=args.thread, is_subagent=args.subagent, user_role=args.role)
    verdict = cfg.policy.evaluate(ctx)
    print(f"判定    : {verdict.effect.value}")
    print(f"命中规则: {verdict.rule_id}　风险: {verdict.risk}　授权范围: {verdict.grant_scope}　TTL: {verdict.ttl_seconds or '仅本次'}")
    print(f"原因    : {verdict.reason}")
    print(f"指纹    : {verdict.fingerprint}")
    if args.explain:
        print("\n逐条规则命中情况：")
        for rule_id, hit in cfg.policy.explain(ctx):
            print(f"  {'✓' if hit else ' '} {rule_id}")
    return 0


def cmd_validate(args) -> int:
    """只校验配置能否加载、规则是否合法。适合进 CI。"""
    try:
        cfg = load_config(args.config)
    except Exception as exc:  # noqa: BLE001 —— CLI 边界，转成可读输出而不是堆栈
        print(f"配置校验失败: {exc}", file=sys.stderr)
        return 1
    print(f"规则数    : {len(cfg.policy.rules)}")
    print(f"默认判定  : {cfg.policy.default_effect.value}")
    print(f"审批模式  : {cfg.approval_mode}")
    print(f"预算层级  : {', '.join(cfg.budget._limits) or '（未配置）'}")
    print(f"账本      : {cfg.db_path}")
    print("配置校验通过")
    return 0


def build_parser() -> argparse.ArgumentParser:
    config_help = "governance.yaml 路径（默认读 DEERFLOW_GOVERNANCE_CONFIG 或 ./governance.yaml）"
    global_config_parent = argparse.ArgumentParser(add_help=False)
    global_config_parent.add_argument("--config", dest="_global_config", default=None, help=config_help)
    command_config_parent = argparse.ArgumentParser(add_help=False)
    command_config_parent.add_argument("--config", dest="config", default=None, help=config_help)

    p = _ConfigArgumentParser(prog="governance", description="DeerFlow 治理插件：审批 / 审计 / 预算", parents=[global_config_parent])
    sub = p.add_subparsers(dest="command", required=True)

    q = sub.add_parser("pending", help="待审批队列", parents=[command_config_parent])
    q.add_argument("-n", "--limit", type=int, default=30)
    q.set_defaults(func=cmd_pending)

    s = sub.add_parser("show", help="审批单详情", parents=[command_config_parent])
    s.add_argument("ticket_id")
    s.set_defaults(func=cmd_show)

    for name, fn, help_text in (("approve", cmd_approve, "批准"), ("deny", cmd_deny, "驳回")):
        d = sub.add_parser(name, help=help_text, parents=[command_config_parent])
        d.add_argument("ticket_id")
        d.add_argument("--by", required=True, help="裁决人，会写进审计账本")
        d.add_argument("--note", default="", help="裁决意见")
        d.set_defaults(func=fn)

    a = sub.add_parser("audit", help="审计账本", parents=[command_config_parent])
    a.add_argument("-n", "--limit", type=int, default=40)
    a.add_argument("--thread", default=None)
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_audit)

    sub.add_parser("stats", help="治理概览", parents=[command_config_parent]).set_defaults(func=cmd_stats)
    sub.add_parser("expire", help="清理过期批准", parents=[command_config_parent]).set_defaults(func=cmd_expire)
    sub.add_parser("validate", help="校验配置（可进 CI）", parents=[command_config_parent]).set_defaults(func=cmd_validate)

    m = sub.add_parser("simulate", help="干跑策略，不落库", parents=[command_config_parent])
    m.add_argument("--tool", required=True)
    m.add_argument("--arg", action="append", help="key=value，可重复")
    m.add_argument("--thread", default="sim")
    m.add_argument("--role", default=None)
    m.add_argument("--subagent", action="store_true")
    m.add_argument("--explain", action="store_true", help="打印每条规则是否命中")
    m.set_defaults(func=cmd_simulate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
