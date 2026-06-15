"""Batch render UI components from a charts.json file path."""
from __future__ import annotations

import json
from pathlib import Path

from langchain.tools import tool
from langgraph.config import get_config

from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.tools.builtins.render_ui_tool import render_ui_tool

# LangChain @tool 装饰器返回 StructuredTool 对象，不能直接调用
# 通过 .func 访问底层原始函数
_render_ui = getattr(render_ui_tool, "func", render_ui_tool)


@tool("render_charts_file")
def render_charts_file(charts_json_path: str) -> str:
    """批量渲染 charts.json 文件中的所有图表。

    这个工具接受 charts.json 文件的路径（支持沙箱虚拟路径如 /mnt/user-data/outputs/charts.json），
    自动转换为物理路径后读取文件，然后逐个调用 render_ui 渲染所有图表。

    Agent 只需调用一次这个工具，而不需要调用 N 次 render_ui。

    Args:
        charts_json_path: charts.json 文件的路径，支持沙箱虚拟路径，例如 /mnt/user-data/outputs/charts.json

    Returns:
        渲染结果摘要，包含成功和失败的图表数量
    """
    config = get_config()
    thread_id = config.get("configurable", {}).get("thread_id")

    # 解析虚拟路径为物理路径
    path = Path(charts_json_path)
    if thread_id and charts_json_path.startswith("/mnt/user-data/"):
        try:
            actual_path = get_paths().resolve_virtual_path(
                thread_id, charts_json_path, user_id=get_effective_user_id()
            )
            path = Path(actual_path)
        except Exception:
            try:
                actual_path = get_paths().resolve_virtual_path(thread_id, charts_json_path)
                path = Path(actual_path)
            except Exception:
                pass

    if not path.exists():
        return f"错误：文件不存在 {charts_json_path} (物理路径: {path})"

    try:
        with open(path, encoding="utf-8") as f:
            charts_data = json.load(f)
    except Exception as e:
        return f"错误：无法读取文件 {e}"

    charts = charts_data.get("charts", [])
    if not charts:
        return "错误：charts.json 中没有图表数据"

    success_count = 0
    error_count = 0
    errors = []

    for i, chart in enumerate(charts):
        chart_type = chart.get("chart_type")
        props = chart.get("props", {})

        component_map = {
            "card": "card",
            "trend": "echart",
            "waveform": "echart",
            "spectrum": "echart",
            "table": "table",
            "markdown": "markdown",
        }

        component = component_map.get(chart_type)
        if not component:
            error_count += 1
            errors.append(f"图表 {i}: 未知的 chart_type '{chart_type}'")
            continue

        try:
            # StructuredTool 不能直接调用，用 .func 访问底层函数
            result = _render_ui(
                component=component,
                props=props,
                interactive=False,
                callback_id=None,
                callback_timeout_ms=None,
                parent_id=None,
                block_id=None,
                action="create",
                sequence=i,
                functional_interaction=False,
            )

            if "error" in result.lower() or "Error:" in result:
                error_count += 1
                errors.append(f"图表 {i} ({chart_type}): {result}")
            else:
                success_count += 1

        except Exception as e:
            error_count += 1
            errors.append(f"图表 {i} ({chart_type}): 异常 {e}")

    summary = f"批量渲染完成：成功 {success_count} 个，失败 {error_count} 个"
    if errors:
        summary += "\n失败详情：\n" + "\n".join(errors[:5])
        if len(errors) > 5:
            summary += f"\n... 还有 {len(errors) - 5} 个错误"

    return summary
