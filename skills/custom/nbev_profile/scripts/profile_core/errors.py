"""
errors.py — 结构化错误体系

harness engineering 原则：每个错误都"可机读 + 可复述 + 可恢复判定"。
统一一个 SkillError，所有失败路径都抛它，由入口统一转成 envelope。
"""

from __future__ import annotations


class SkillError(Exception):
    """所有业务/校验/运行时错误的统一基类。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str = "",
        fields: list[str] | None = None,
        retryable: bool = False,
    ):
        self.code = code
        self.message = message
        self.hint = hint
        self.fields = fields or []
        self.retryable = retryable
        super().__init__(message)

    def to_error(self) -> dict:
        return {
            "error_code": self.code,
            "message": self.message,
            "hint": self.hint,
            "fields": self.fields,
            "retryable": self.retryable,
        }


# 语义化子类（便于 except 精确捕获，也让代码自解释）
class ValidationError(SkillError):
    """入参非法（格式/范围/必填）。不可重试。"""


class ApiError(SkillError):
    """调用后端测算接口失败。是否可重试取决于具体场景。"""




class NeedClarify(SkillError):
    """必填信息缺失，需向用户澄清而非报错或猜测。"""

    def __init__(self, message: str, *, hint: str, fields: list[str]):
        super().__init__(
            code="NEED_CLARIFY",
            message=message,
            hint=hint,
            fields=fields,
            retryable=False,
        )
