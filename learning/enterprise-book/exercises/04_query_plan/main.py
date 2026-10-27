"""企业 E03：用字典描述查询，并检查程序支持的指标与分组方式。

题目：查《三体》2026年8月每天的净发货量。
本轮在指标和分组检查之后，增加日期解析与范围检查。
SQL 编译、数据库查询和模型调用在后续接入。
"""

from datetime import datetime
from pprint import pprint

from date_utils import validate_date_range

# 程序内部约定的名称；后续由代码映射到查询逻辑。
ALLOWED_METRICS = {"shipment", "return", "net_shipment"}
ALLOWED_GROUPS = {"total", "day"}


def validate_query_plan(plan: dict) -> None:
    """检查指标、分组方式及日期。

    本轮约定五个字段均已存在、值均为字符串。
    指标或分组方式不支持时，抛出带原因的 ValueError。
    日期字符串按年月日解析，起始日期必须早于截止日期。
    上述检查均通过时正常结束，无需返回 True。
    书名检查留待后续；本轮不修改传入字典。
    """
    # TODO：检查 plan["metric"] 和 plan["group_by"]。
    # 删除占位异常，自行实现两个字段的检查。
    if plan["metric"] not in ALLOWED_METRICS or plan["group_by"] not in ALLOWED_GROUPS:
        raise ValueError("字典接受了错误的值")

    # TODO：把 plan 中的两个日期字符串分别解析为 datetime 对象，
    # 保存到局部变量 start_date、end_date，使用格式 "%Y-%m-%d"。
    # 然后调用上面已经导入的 validate_date_range 检查这两个对象。
    # strptime 自身会对不存在或无法按格式解析的日期抛出 ValueError。
    # 删除以下占位异常，填写你的实现；这里先让异常传给调用方。
    start_date = datetime.strptime(plan["start_date"],"%Y-%m-%d")
    end_date = datetime.strptime(plan["end_date"],"%Y-%m-%d")
    return validate_date_range(start_date,end_date)

# TODO：根据题目补齐五个值。日期先用 YYYY-MM-DD 字符串表达。
query_plan = {
    "book_name": "三体",
    "metric": "net_shipment",  # shipment=发货量，return=退货量，net_shipment=净发货量
    "start_date": "2026-08-01",
    "end_date": "2026-09-01",  # 不包含该日期
    "group_by": "day",  # total=整个范围汇总，day=每天一组

}


if __name__ == "__main__":
    validate_query_plan(query_plan)
    print("指标、分组方式及日期检查通过，当前计划：")
    pprint(query_plan, sort_dicts=False)

    # 完成后分别试一下：
    # 1. 题目中的计划：正常结束并打印字典。
    # 2. 只把 metric 改为 profit：应拒绝，当前未实现利润指标。
    # 3. 恢复合法指标，只把 group_by 改为 author：应拒绝。
    # 4. 恢复合法指标与分组，起始日期改为2026-02-30：应拒绝。
    # 5. 起始日期为2026-09-01、截止日期为2026-08-01：应拒绝。
    # 6. 起止日期相等：应拒绝。
