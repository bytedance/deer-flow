"""企业 E01：把已写好的 SQL 接到 Python 查询函数。

调用方提供已经建立的数据库连接和已经确认的查询文本。
本轮由学习者实现参数范围校验、执行、取结果和返回值。
暂时约定 limit 是整数；本文件不保存连接地址、账号或密码。
"""


def search_books(
    connection,
    sql: str,
    book_name: str,
    limit: int = 20,
) -> list[tuple]:
    """按书名查询，返回最多 limit 行，每行是一个元组。

    sql 使用 :book_name 绑定参数。
    查询成功但无匹配时返回 []；数据库异常继续向调用方抛出。
    limit<=0 时抛出 ValueError，不执行数据库操作。
    本轮 fetchmany 只限制本次取回的行数；SQL 执行限制随后补充。
    """
    # TODO 1：检查 limit；如果小于等于 0，抛出 ValueError。
    if limit <= 0:
        raise ValueError("limit必须大于0")
    with connection.cursor() as cursor:
        # TODO 2：使用 execute 执行 sql，通过字典传入 book_name。
        cursor.execute(sql,{"book_name": book_name})
        # TODO 3：使用 fetchmany，取回最多 limit 行。
        rows = cursor.fetchmany(limit)
        # TODO 4：返回取回的结果；不要用 print 代替 return。
    return rows


def execute_query(
    connection,
    sql: str,
    params: dict,
    limit: int = 20,
) -> list[tuple]:
    """执行调用方提供的已确认查询，使用 params 绑定参数。

    查询图书时，params 可以是 {"book_name": "SQL入门"}。
    查询库存时，params 可以是 {"book_id": 101}（101 仅为示意 ID）。
    保留原函数的数量校验、空结果与异常传播行为。
    本函数只负责执行；SQL 和访问范围的校验由调用方负责。
    """
    # TODO：参考上方 search_books，自己实现这个通用函数。
    # 关键变化：execute 的第二个参数直接使用调用方传入的 params。
    # 原 search_books 先保留，现有查书入口仍可运行；验收后再切换调用。
    if limit <= 0:
        raise ValueError("limit必须大于0")
    with connection.cursor() as cursor:
        cursor.execute(sql,params)
        # TODO 3：使用 fetchmany，取回最多 limit 行。
        rows = cursor.fetchmany(limit)
        # TODO 4：返回取回的结果；不要用 print 代替 return。
    return rows


if __name__ == "__main__":
    print("本文件定义查询函数。请运行 logs/enterprise-book/lessons/02_run_query.py 执行真实查询。")
