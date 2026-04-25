# MySQL 工具 + Skill POC

最小化示例：自定义 MySQL 查询工具 + Skill 扩展。

## 文件结构

```
deerflow-extension-demo/
├── README.md                    # 本文件
├── config.yaml                  # DeerFlow 配置
├── extensions_config.json       # 扩展配置（Skills 启用）
├── main.py                      # 测试入口
├── mysql_tools.py               # MySQL 工具实现
└── skills/
    └── mysql-guide/
        └── SKILL.md             # MySQL 查询助手 Skill
```

## 依赖安装

```bash
pip install sqlalchemy pymysql pandas langchain-core langchain-deepseek
```

## 运行

```bash
cd /Users/frankliu/Code/deerflow/backend
PYTHONPATH=/Users/frankliu/Code/deerflow/examples/deerflow-extension-demo uv run python /Users/frankliu/Code/deerflow/examples/deerflow-extension-demo/main.py
```

## 扩展内容

### 1. Tools（工具）

| 工具名 | 说明 |
|---|------|
| `mysql_query` | 执行 SELECT 查询 |
| `mysql_list_tables` | 列出所有表 |
| `mysql_describe_table` | 查看表结构 |

### 2. Skill（技能）

`mysql-guide` Skill 提供：
- 数据库概述说明
- 常用查询示例
- 使用流程指导

Skill 内容会被注入到 Agent 的 system prompt 中，指导 Agent 如何更好地使用 MySQL 工具。

## 数据库信息

- 数据库：Sakila 电影示例数据库
- 地址：rm-bp1ro28t9mm34p058to.mysql.rds.aliyuncs.com:3306/movie_example