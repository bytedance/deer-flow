"""DeerFlow 生产治理插件：人工审批闸 + 合规审计账本 + 分层成本预算熔断。

核心层（policy / fingerprint / budget / pricing / store / engine）零三方依赖，
可在没有 DeerFlow 与 langchain 的环境里被完整单测。
适配层（provider / middleware）按需 import，因此不在这里做顶层导出 ——
`import deerflow_governance` 不应该因为宿主环境缺 langchain 而失败。
"""

__version__ = "0.1.0"

from .contracts import BudgetLevel, CallContext, Effect, TicketStatus, Usage, Verdict
from .engine import ApprovalEngine, Decision
from .policy import PolicyEngine, Rule

__all__ = [
    "ApprovalEngine",
    "BudgetLevel",
    "CallContext",
    "Decision",
    "Effect",
    "PolicyEngine",
    "Rule",
    "TicketStatus",
    "Usage",
    "Verdict",
    "__version__",
]
