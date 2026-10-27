"""企业 E02：在执行查询前检查日期范围。

本练习只使用示例日期，不连接数据库。
"""

from datetime import datetime


def validate_date_range(start_date: datetime, end_date: datetime) -> None:
    """检查包含起点、不包含终点的查询范围。

    本轮约定传入的两个参数已经是无时区的 datetime 对象。
    起始日期必须早于截止日期；不符合时抛出 ValueError 并说明原因。
    合法时正常结束，无需返回 True，也不负责打印或查询数据库。
    """
    # TODO：删除下面的占位异常，自行完成检查。
    if start_date >= end_date:
        raise ValueError("查询日期不合法")


if __name__ == "__main__":
    start = datetime(2026, 8, 1)
    end = datetime(2026, 9, 1)
    validate_date_range(start, end)
    print("日期范围合法，可以继续查询。")

    # 完成后分别修改 start、end，再运行，检查三种情况：
    # 1. 8月1日到9月1日：正常结束并打印上面的提示。
    # 2. 9月1日到8月1日：抛出 ValueError，不打印“日期范围合法”。
    # 3. 8月1日到8月1日：同样抛出 ValueError。
