---
name: pyecharts-viz-examples
description: 生成 pyecharts 可视化示例代码。当用户需要创建 pyecharts 图表、查看图表示例、了解图表用法或生成数据可视化代码时使用此技能。支持 49 种图表类型：基础图表 (Bar、Line、Pie、Scatter、Map 等 31 种)、复合图表 (Grid、Page、Tab、Timeline)、3D 图表 (Bar3D、Line3D、Scatter3D 等 8 种) 和 Echarts 6 新图表 (Violin、Stage 等 6 种)。
---

# pyecharts 可视化示例生成

## 快速开始

生成 pyecharts 图表示例的基本步骤：

1. **确定图表类型** - 根据用户需求选择合适的图表类型
2. **查找示例** - 从 `references/chart_types.md` 查找对应示例代码
3. **修改数据** - 根据用户数据替换示例中的测试数据
4. **渲染输出** - 调用 `.render()` 生成 HTML 文件或 `.render_notebook()` 在 Notebook 中使用

## 图表类型概览

详细图表类型和示例代码见 `references/chart_types.md`。

| 类别 | 图表数量 | 主要类型 |
|------|---------|---------|
| 基础图表 | 31 种 | Bar、Line、Pie、Scatter、Map、Geo、Graph、HeatMap 等 |
| 复合图表 | 4 种 | Grid、Page、Tab、Timeline |
| 3D 图表 | 8 种 | Bar3D、Line3D、Scatter3D、Surface3D、Map3D、MapGlobe 等 |
| Echarts 6 新图表 | 6 种 | Violin、Stage、SegmentedDoughnut、Contour、BarRange、LineRange |

**总计支持 49 种图表类型**

## 核心能力

1. **生成示例代码** - 提供任何图表类型的完整可运行示例
2. **使用 Faker 测试数据** - 快速生成测试数据进行验证
3. **图表组合** - 使用 Grid、Page、Tab、Timeline 组合多个图表
4. **地图集成** - 支持中国地图、世界地图，以及百度/高德/Google/Leaflet 地图
5. **输出配置** - HTML 文件、图片 (需 snapshot_selenium)、Notebook

## 标准图表结构

```python
from pyecharts import options as opts
from pyecharts.charts import [图表类型]

chart = (
    [ChartType]()
    .add_xaxis([...])  # XY 轴图表需要
    .add_yaxis("系列名", [...])
    .set_global_opts(
        title_opts=opts.TitleOpts(title="图表标题"),
        xaxis_opts=opts.AxisOpts(),
        yaxis_opts=opts.AxisOpts(),
    )
)
chart.render("output.html")
```

## 常用配置项速查

### 全局配置 (set_global_opts)
- `title_opts` - 标题配置
- `legend_opts` - 图例配置
- `tooltip_opts` - 提示框配置
- `xaxis_opts` / `yaxis_opts` - 坐标轴配置
- `visualmap_opts` - 视觉映射配置
- `datazoom_opts` - 区域缩放配置

### 系列配置
- `label_opts` - 标签样式
- `itemstyle_opts` - 图形样式
- `linestyle_opts` - 线样式
- `markpoint_opts` / `markline_opts` - 标记点/线

## 输出配置

### 渲染为 HTML 文件
```python
chart.render("chart.html")
```

### 渲染为图片（需要额外依赖）
```python
from snapshot_selenium import snapshot as driver
from pyecharts.render import make_snapshot

make_snapshot(driver, chart.render(), "chart.png")
```

### Notebook 环境
```python
chart.render_notebook()
```

## 参考资料

- **详细图表类型和示例**: `references/chart_types.md`
- **pyecharts 官方文档**: https://pyecharts.org
- **示例画廊**: https://gallery.pyecharts.org
