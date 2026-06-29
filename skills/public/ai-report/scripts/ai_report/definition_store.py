from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from ai_report.models import ComputeRecord, MetricRecord, ReportRecord, SectionRecord, TableRecord


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def connect_definitions(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path))


def init_definition_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        -- 报告主表：长生命周期，每条 report_id 一行
        CREATE TABLE IF NOT EXISTS reports(
          report_id TEXT PRIMARY KEY,        -- 报告唯一 ID
          report_name TEXT,                  -- 报告内部名（slug）
          report_title TEXT,                 -- 报告对外展示标题
          status TEXT,                       -- 状态：active / draft / archived
          version INTEGER,                   -- 报告版本号（每次激活递增）
          last_preview_run_id TEXT,          -- 最近一次预览 run_id
          activated_run_id TEXT,             -- 当前激活版本对应的 run_id
          created_at TIMESTAMP DEFAULT current_timestamp,  -- 创建时间
          updated_at TIMESTAMP DEFAULT current_timestamp,  -- 更新时间
          metadata JSON                      -- 扩展元数据 JSON
        )
    """)
    con.execute("""
        -- 报告章节表：每个章节在所属 report_id 下唯一
        CREATE TABLE IF NOT EXISTS report_sections(
          section_id TEXT PRIMARY KEY,       -- 章节唯一 ID
          report_id TEXT,                    -- 所属报告 ID
          section_key TEXT,                  -- 章节业务 key（用于跨报告复用/排序）
          section_title TEXT,                -- 章节对外展示标题
          section_order INTEGER,             -- 章节在报告内的顺序
          description_prompt TEXT,           -- 章节级描述生成 prompt
          enabled BOOLEAN,                   -- 是否启用（运行时只跑 enabled=true）
          metadata JSON,                     -- 扩展元数据 JSON
          created_at TIMESTAMP DEFAULT current_timestamp,  -- 创建时间
          updated_at TIMESTAMP DEFAULT current_timestamp   -- 更新时间
        )
    """)
    con.execute("""
        -- 报告表格表：每张表在所属 report_id 下唯一
        CREATE TABLE IF NOT EXISTS report_tables(
          table_id TEXT PRIMARY KEY,            -- 表格唯一 ID
          report_id TEXT,                       -- 所属报告 ID
          section_id TEXT,                      -- 所属章节 ID
          table_title TEXT,                     -- 表格对外展示标题
          table_order INTEGER,                  -- 表格在章节内的顺序
          source_md_path TEXT,                  -- 原始 table.md 源文件路径
          source_md_hash TEXT,                  -- 原始文件 hash（用于变更检测）
          parsed_payload JSON,                  -- table.md 解析后的完整结构 JSON
          headers JSON,                         -- 二维表头结构 JSON
          orgs JSON,                            -- 适用机构列表 JSON
          time_info JSON,                       -- 时间信息 JSON（期间别名等）
          description_prompt TEXT,              -- 表格级描述生成 prompt
          approval_status TEXT,                 -- 审批状态：draft / approved
          query_failure_policy TEXT,            -- 查询失败处理策略：continue_with_sentinel / stop_on_failure
          compute_failure_policy TEXT,          -- 计算失败处理策略
          description_failure_policy TEXT,      -- 描述生成失败处理策略
          last_design_run_id TEXT,              -- 最近一次设计 run_id
          created_at TIMESTAMP DEFAULT current_timestamp,  -- 创建时间
          updated_at TIMESTAMP DEFAULT current_timestamp   -- 更新时间
        )
    """)
    con.execute("""
        -- 指标表：每行是一个 (表格, 指标, 期间别名) 三元组
        CREATE TABLE IF NOT EXISTS table_metrics(
          table_id TEXT,                      -- 所属表格 ID
          idx_id TEXT,                        -- 指标 idx_id（业务指标唯一标识）
          period_alias TEXT,                  -- 期间别名（本期 / 去年同期 / 上期 ...）
          data_unit TEXT,                     -- 数据单位（元 / 万元 / % ...）
          header_text TEXT,                   -- 表头展示文本
          metric_order INTEGER,               -- 指标在表内的顺序
          approval_status TEXT,               -- 审批状态：draft / approved
          last_design_run_id TEXT,            -- 最近一次设计 run_id
          metadata JSON,                      -- 扩展元数据 JSON
          PRIMARY KEY(table_id, idx_id, period_alias)
        )
    """)
    con.execute("""
        -- 计算列表：每行定义一个由 metric_facts 派生的派生指标
        CREATE TABLE IF NOT EXISTS table_computes(
          compute_id TEXT PRIMARY KEY,         -- 计算列唯一 ID
          table_id TEXT,                       -- 所属表格 ID
          compute_name TEXT,                   -- 计算列对外展示名（支持中文）
          formula_text TEXT,                   -- 公式自然语言描述
          compute_sql TEXT,                    -- 实际执行的 SQL（读 table_frame）
          dependencies JSON,                   -- 依赖指标列表 JSON
          examples JSON,                       -- 公式示例 JSON（用于文档/调试）
          approval_status TEXT,                -- 审批状态：draft / approved
          last_design_run_id TEXT,             -- 最近一次设计 run_id
          created_at TIMESTAMP DEFAULT current_timestamp,  -- 创建时间
          updated_at TIMESTAMP DEFAULT current_timestamp   -- 更新时间
        )
    """)
    con.execute("""
        -- 设计阶段产物表：记录每次设计 run 产生的中间文件（预览图 / 中间报告等）
        CREATE TABLE IF NOT EXISTS design_artifacts(
          artifact_id TEXT PRIMARY KEY,        -- 产物唯一 ID
          report_id TEXT,                      -- 所属报告 ID
          table_id TEXT,                       -- 关联表格 ID（可空，报告级产物时为空）
          design_run_id TEXT,                  -- 产出该产物的设计 run_id
          output_id TEXT,                      -- 关联的 run_outputs.output_id
          artifact_type TEXT,                  -- 产物类型：preview / intermediate / design_md
          file_path TEXT,                      -- 产物文件路径
          status TEXT,                         -- 状态：pending / ready / failed
          created_at TIMESTAMP DEFAULT current_timestamp  -- 创建时间
        )
    """)


def upsert_report(con: duckdb.DuckDBPyConnection, record: ReportRecord) -> None:
    con.execute("""
        INSERT OR REPLACE INTO reports(
          report_id, report_name, report_title, status, version,
          last_preview_run_id, activated_run_id, metadata, updated_at
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?::JSON, current_timestamp)
    """, [record.report_id, record.report_name, record.report_title, record.status, record.version, _json(record.metadata)])


def upsert_section(con: duckdb.DuckDBPyConnection, record: SectionRecord) -> None:
    con.execute("""
        INSERT OR REPLACE INTO report_sections(
          section_id, report_id, section_key, section_title, section_order,
          description_prompt, enabled, metadata, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?::JSON, current_timestamp)
    """, [
        record.section_id,
        record.report_id,
        record.section_key,
        record.section_title,
        record.section_order,
        record.description_prompt,
        record.enabled,
        _json(record.metadata),
    ])


def upsert_table(con: duckdb.DuckDBPyConnection, record: TableRecord) -> None:
    con.execute("""
        INSERT OR REPLACE INTO report_tables(
          table_id, report_id, section_id, table_title, table_order,
          source_md_path, source_md_hash, parsed_payload, headers, orgs,
          time_info, description_prompt, approval_status, query_failure_policy,
          compute_failure_policy, description_failure_policy, last_design_run_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?::JSON, ?::JSON, ?, ?, ?, ?, ?, ?, current_timestamp)
    """, [
        record.table_id,
        record.report_id,
        record.section_id,
        record.table_title,
        record.table_order,
        record.source_md_path,
        record.source_md_hash,
        _json(record.parsed_payload),
        _json(record.headers),
        _json(record.orgs),
        _json(record.time_info),
        record.description_prompt,
        record.approval_status,
        record.query_failure_policy,
        record.compute_failure_policy,
        record.description_failure_policy,
        record.last_design_run_id,
    ])


def upsert_metric(con: duckdb.DuckDBPyConnection, record: MetricRecord) -> None:
    con.execute("""
        INSERT OR REPLACE INTO table_metrics(
          table_id, idx_id, period_alias, data_unit, header_text,
          metric_order, approval_status, last_design_run_id, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)
    """, [
        record.table_id,
        record.idx_id,
        record.period_alias,
        record.data_unit,
        record.header_text,
        record.metric_order,
        record.approval_status,
        record.last_design_run_id,
        _json(record.metadata),
    ])


def upsert_compute(con: duckdb.DuckDBPyConnection, record: ComputeRecord) -> None:
    con.execute("""
        INSERT OR REPLACE INTO table_computes(
          compute_id, table_id, compute_name, formula_text, compute_sql,
          dependencies, examples, approval_status, last_design_run_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?, ?, current_timestamp)
    """, [
        record.compute_id,
        record.table_id,
        record.compute_name,
        record.formula_text,
        record.compute_sql,
        _json(record.dependencies),
        _json(record.examples),
        record.approval_status,
        record.last_design_run_id,
    ])


def _rows(con: duckdb.DuckDBPyConnection, query: str, params: list[Any]) -> list[dict[str, Any]]:
    result = con.execute(query, params)
    names = [d[0] for d in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def load_active_report(con: duckdb.DuckDBPyConnection, report_id: str) -> dict[str, Any]:
    reports = _rows(con, "SELECT * FROM reports WHERE report_id = ? AND status = 'active'", [report_id])
    if not reports:
        raise ValueError(f"Active report not found: {report_id}")
    sections = _rows(con, """
        SELECT * FROM report_sections
        WHERE report_id = ? AND enabled = true
        ORDER BY section_order, section_id
    """, [report_id])
    tables = _rows(con, """
        SELECT * FROM report_tables
        WHERE report_id = ? AND approval_status = 'approved'
        ORDER BY section_id, table_order, table_id
    """, [report_id])
    table_ids = [row["table_id"] for row in tables]
    if table_ids:
        placeholders = ",".join(["?"] * len(table_ids))
        metrics = _rows(con, f"""
            SELECT * FROM table_metrics
            WHERE table_id IN ({placeholders}) AND approval_status = 'approved'
            ORDER BY table_id, metric_order, idx_id, period_alias
        """, table_ids)
        computes = _rows(con, f"""
            SELECT * FROM table_computes
            WHERE table_id IN ({placeholders}) AND approval_status = 'approved'
            ORDER BY table_id, compute_name
        """, table_ids)
    else:
        metrics = []
        computes = []
    return {
        "report": reports[0],
        "sections": sections,
        "tables": tables,
        "metrics": metrics,
        "computes": computes,
    }