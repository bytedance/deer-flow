"""供查询计划练习导入；沿用上一题已验证的日期范围校验实现。"""

from datetime import datetime


def validate_date_range(start_date: datetime, end_date: datetime) -> None:
    """两个参数均为无时区 datetime，起始日期必须早于截止日期。"""
    if start_date >= end_date:
        raise ValueError("查询日期不合法")
