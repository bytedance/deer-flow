#!/usr/bin/env python3
"""MySQL 工具 - 最小 POC。

连接 Sakila 示例数据库，提供查询能力。
"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field


# 数据库连接字符串
DB_CONNECTION = "mysql+pymysql://fish:32KjyZ_uW9L9_Q5@rm-bp1ro28t9mm34p058to.mysql.rds.aliyuncs.com:3306/movie_example"


class MySQLQueryInput(BaseModel):
    """SQL 查询输入参数。"""

    sql: str = Field(description="SELECT 查询语句（只支持 SELECT）")
    limit: int = Field(default=20, ge=1, le=100, description="返回行数限制，默认 20")


@tool(args_schema=MySQLQueryInput)
def mysql_query(sql: str, limit: int = 20) -> str:
    """执行 MySQL 查询并返回结果。

    只支持 SELECT 语句，用于查询电影数据库。

    Args:
        sql: SELECT 查询语句
        limit: 返回行数限制

    Returns:
        查询结果的格式化字符串
    """
    # 安全检查：只允许 SELECT
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        return "错误：只支持 SELECT 查询语句"

    # 添加 LIMIT（如果没有）
    if "LIMIT" not in sql_upper:
        sql = f"{sql.rstrip(';')} LIMIT {limit}"

    try:
        import pandas as pd
        from sqlalchemy import create_engine

        # 创建数据库连接
        engine = create_engine(DB_CONNECTION)

        # 执行查询
        df = pd.read_sql(sql, engine)

        if df.empty:
            return "查询结果为空"

        # 格式化输出
        result = f"查询返回 {len(df)} 行数据：\n\n"
        result += df.to_string(index=False, max_rows=limit)

        return result

    except ImportError:
        return "错误：请安装依赖 pip install sqlalchemy pymysql pandas"
    except Exception as e:
        return f"查询失败：{e}"


@tool
def mysql_list_tables() -> str:
    """列出数据库中所有表。"""
    try:
        from sqlalchemy import create_engine, inspect

        engine = create_engine(DB_CONNECTION)
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        if not tables:
            return "数据库中没有表"

        return f"数据库中的表（共 {len(tables)} 个）：\n" + "\n".join(f"- {t}" for t in tables)

    except ImportError:
        return "错误：请安装依赖 pip install sqlalchemy pymysql"
    except Exception as e:
        return f"查询失败：{e}"


@tool
def mysql_describe_table(table_name: str) -> str:
    """查看表结构。

    Args:
        table_name: 表名
    """
    try:
        from sqlalchemy import create_engine, inspect

        engine = create_engine(DB_CONNECTION)
        inspector = inspect(engine)
        columns = inspector.get_columns(table_name)

        if not columns:
            return f"表 '{table_name}' 不存在或没有列"

        lines = [f"表 '{table_name}' 的结构：\n"]
        lines.append(f"{'列名':<20} {'类型':<15} {'可空':<5} {'主键':<5}")
        lines.append("-" * 50)

        for col in columns:
            name = col.get("name", "")
            type_ = str(col.get("type", ""))
            nullable = "是" if col.get("nullable", True) else "否"
            primary = "是" if col.get("primary_key", False) else "否"
            lines.append(f"{name:<20} {type_:<15} {nullable:<5} {primary:<5}")

        return "\n".join(lines)

    except ImportError:
        return "错误：请安装依赖 pip install sqlalchemy pymysql"
    except Exception as e:
        return f"查询失败：{e}"


if __name__ == "__main__":
    # 测试工具
    print("=== 测试 MySQL 工具 ===\n")

    print("1. 列出所有表：")
    print(mysql_list_tables.invoke({}))
    print()

    print("2. 查看表结构：")
    print(mysql_describe_table.invoke({"table_name": "actor"}))
    print()

    print("3. 执行查询：")
    print(mysql_query.invoke({"sql": "SELECT * FROM actor LIMIT 5"}))
