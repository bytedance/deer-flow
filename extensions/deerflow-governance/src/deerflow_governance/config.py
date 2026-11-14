"""governance.yaml 加载。唯一配置入口，业务代码里不出现 os.environ。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .budget import BudgetLedger
from .policy import PolicyEngine
from .pricing import PriceBook
from .store import GovernanceStore

DEFAULT_CONFIG_ENV = "DEERFLOW_GOVERNANCE_CONFIG"


@dataclass
class GovernanceConfig:
    policy: PolicyEngine
    budget: BudgetLedger
    prices: PriceBook
    db_path: Path
    jsonl_path: Path | None
    approval_mode: str = "ticket"
    fail_closed: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    def build_store(self) -> GovernanceStore:
        return GovernanceStore(self.db_path, jsonl_path=self.jsonl_path)


def _resolve(base: Path, value: str | None, default: str) -> Path:
    p = Path(value or default)
    return p if p.is_absolute() else (base / p)


def load(path: str | Path | None = None) -> GovernanceConfig:
    """按优先级解析配置文件路径：显式参数 > 环境变量 > ./governance.yaml。"""
    import yaml

    candidate = path or os.environ.get(DEFAULT_CONFIG_ENV) or "governance.yaml"
    cfg_path = Path(candidate).expanduser().resolve()
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"找不到治理配置 {cfg_path}。"
            f"请复制 governance.example.yaml 并通过 {DEFAULT_CONFIG_ENV} 指向它。"
        )
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    base = cfg_path.parent

    storage = data.get("storage") or {}
    return GovernanceConfig(
        policy=PolicyEngine.from_dict(data.get("policy") or {}),
        budget=BudgetLedger.from_dict(data.get("budget") or {}),
        prices=PriceBook.from_dict(data.get("prices") or {}, strict=bool(data.get("strict_pricing", False))),
        db_path=_resolve(base, storage.get("db_path"), "data/governance.db"),
        jsonl_path=_resolve(base, storage.get("audit_jsonl"), "data/audit.jsonl") if storage.get("audit_jsonl", True) else None,
        approval_mode=str(data.get("approval_mode", "ticket")),
        fail_closed=bool(data.get("fail_closed", True)),
        raw=data,
    )
