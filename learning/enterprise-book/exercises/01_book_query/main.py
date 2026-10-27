"""企业项目练习 01：按作者查询图书。

使用合成记录练习查询逻辑，后续再连接数据库和 Agent。
本轮假定 limit 是正整数，参数校验放到后续步骤。
"""


BOOKS = [
    {"id": 1, "title": "示例图书 A", "author": "刘慈欣"},
    {"id": 2, "title": "示例图书 B", "author": "余华"},
    {"id": 3, "title": "示例图书 C", "author": "刘慈欣"},
    {"id": 4, "title": "示例图书 D", "author": "王小波"},
    {"id": 5, "title": "示例图书 E", "author": "刘慈欣"},
]


def search_books(author: str, limit: int = 5) -> list[dict]:
    """按作者精确匹配，保持 BOOKS 中的顺序，最多返回 limit 条记录。

    每条结果保留 id、title、author；找不到匹配图书时返回空列表。
    """
    # TODO：在这里实现查询逻辑，替换下面的占位异常。
    result = []
    count = 0
    for i,book in enumerate(BOOKS):
        if book["author"] == author and count < limit:
            result.append(book)
            count += 1
    return result


if __name__ == "__main__":
    result = search_books(author="刘慈欣", limit=2)
    print(result)
    # 完成后，此例应返回示例图书 A 和 C 的完整记录。
