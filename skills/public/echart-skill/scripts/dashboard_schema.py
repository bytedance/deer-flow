"""
Dashboard Schema Models.

Provides pydantic models for dashboard configuration validation:
- ChartPosition: Validates row/col positioning and spans
- ChartConfig: Validates individual chart configuration
- DashboardConfig: Validates overall dashboard layout and overlap detection

Usage:
    from scripts.dashboard_schema import DashboardConfig, get_dashboard_json_schema

    config = DashboardConfig(
        title="My Dashboard",
        columns=3,
        charts=[
            ChartConfig(
                id="chart1",
                position=ChartPosition(row=0, col=0, col_span=2),
                query="SELECT * FROM sales"
            )
        ]
    )

    schema = get_dashboard_json_schema()
"""
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ChartPosition(BaseModel):
    """图表位置配置。

    定义图表在仪表盘网格中的位置和大小。

    Attributes:
        row: 行位置（0索引）
        col: 列位置（0索引）
        row_span: 占用的行数
        col_span: 占用的列数
    """
    row: int = Field(ge=0, description="行位置（0索引）")
    col: int = Field(ge=0, description="列位置（0索引）")
    row_span: int = Field(default=1, ge=1, description="占用的行数")
    col_span: int = Field(default=1, ge=1, description="占用的列数")


class ChartConfig(BaseModel):
    """图表配置。

    定义单个图表的配置，包括位置、查询和ECharts选项。

    Attributes:
        id: 图表唯一标识符
        position: 图表在网格中的位置
        title: 图表标题
        query: SQL查询语句
        echarts_option: ECharts配置对象
        custom_js: 自定义JavaScript代码
    """
    id: str = Field(description="图表唯一标识符")
    position: ChartPosition = Field(description="图表在网格中的位置")
    title: str = Field(default="", description="图表标题")
    query: str = Field(description="SQL查询语句")
    echarts_option: dict[str, Any] = Field(default_factory=dict, description="ECharts配置对象")
    custom_js: str = Field(default="", description="自定义JavaScript代码")


class DashboardConfig(BaseModel):
    """仪表盘配置。

    定义仪表盘的整体布局和图表配置。

    Attributes:
        title: 仪表盘标题
        columns: 网格列数（1-12）
        row_height: 每行高度（像素）
        gap: 图表间距（像素）
        charts: 图表配置列表
        db_path: 数据库路径
    """
    title: str = Field(default="Dashboard", description="仪表盘标题")
    columns: int = Field(default=2, ge=1, le=12, description="网格列数（1-12）")
    row_height: int = Field(default=400, ge=100, description="每行高度（像素）")
    gap: int = Field(default=16, ge=0, description="图表间距（像素）")
    charts: list[ChartConfig] = Field(min_length=1, description="图表配置列表")
    db_path: str = Field(default="workspace.duckdb", description="数据库路径")

    @field_validator('charts')
    @classmethod
    def validate_no_overlapping_positions(cls, v: list[ChartConfig]) -> list[ChartConfig]:
        """验证图表位置不重叠。

        Args:
            v: 图表配置列表

        Returns:
            验证通过的图表列表

        Raises:
            ValueError: 当图表位置重叠时
        """
        occupied_cells: set[tuple[int, int]] = set()

        for chart in v:
            # 计算该图表占用的所有单元格
            for row in range(chart.position.row, chart.position.row + chart.position.row_span):
                for col in range(chart.position.col, chart.position.col + chart.position.col_span):
                    cell = (row, col)
                    if cell in occupied_cells:
                        raise ValueError(
                            f"Chart {chart.id} overlaps with another chart at position {cell}"
                        )
                    occupied_cells.add(cell)

        return v

    @field_validator('charts')
    @classmethod
    def validate_column_bounds(cls, v: list[ChartConfig], info) -> list[ChartConfig]:
        """验证图表不超出网格边界。

        Args:
            v: 图表配置列表
            info: 验证上下文信息

        Returns:
            验证通过的图表列表

        Raises:
            ValueError: 当图表超出网格边界时
        """
        # 获取 columns 值，需要从 data 中获取（因为验证顺序问题）
        columns = info.data.get('columns', 2)

        for chart in v:
            end_col = chart.position.col + chart.position.col_span
            if end_col > columns:
                raise ValueError(
                    f"Chart {chart.id} exceeds grid columns: "
                    f"position {chart.position.col} + span {chart.position.col_span} = {end_col} > {columns}"
                )

        return v


def get_dashboard_json_schema() -> dict[str, Any]:
    """获取仪表盘配置的JSON Schema。

    用于外部工具验证配置格式。

    Returns:
        JSON Schema字典
    """
    return DashboardConfig.model_json_schema()
