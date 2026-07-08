# pyecharts 图表类型参考

本文档记录了 pyecharts 支持的所有图表类型及其基本用法。

## 目录

1. [基础图表 (Basic Charts)](#基础图表)
2. [复合图表 (Composite Charts)](#复合图表)
3. [3D 图表 (Three Axis Charts)](#3d-图表)

---

## 基础图表

### Bar - 柱状图

```python
from pyecharts import options as opts
from pyecharts.charts import Bar

bar = (
    Bar()
    .add_xaxis(["衬衫", "毛衣", "领带", "裤子", "风衣", "高跟鞋", "袜子"])
    .add_yaxis("商家 A", [114, 55, 27, 101, 125, 27, 105])
    .add_yaxis("商家 B", [57, 134, 137, 129, 145, 60, 49])
    .set_global_opts(title_opts=opts.TitleOpts(title="柱状图示例"))
)
```

### Line - 折线图

```python
from pyecharts import options as opts
from pyecharts.charts import Line

line = (
    Line()
    .add_xaxis(["周一", "周二", "周三", "周四", "周五", "周六", "周日"])
    .add_yaxis("销售额", [120, 200, 150, 80, 70, 110, 130])
    .set_global_opts(title_opts=opts.TitleOpts(title="折线图示例"))
)
```

### Pie - 饼图

```python
from pyecharts import options as opts
from pyecharts.charts import Pie

pie = (
    Pie()
    .add(
        "商品",
        [("衬衫", 114), ("毛衣", 55), ("领带", 27), ("裤子", 101), ("风衣", 125)],
        radius=["40%", "75%"],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="饼图示例"))
)
```

### Scatter - 散点图

```python
from pyecharts import options as opts
from pyecharts.charts import Scatter

scatter = (
    Scatter()
    .add_xaxis(["周一", "周二", "周三", "周四", "周五", "周六", "周日"])
    .add_yaxis("销量", [120, 200, 150, 80, 70, 110, 130])
    .set_global_opts(title_opts=opts.TitleOpts(title="散点图示例"))
)
```

### EffectScatter - 带有涟漪特效的散点图

```python
from pyecharts import options as opts
from pyecharts.charts import EffectScatter

es = (
    EffectScatter()
    .add_xaxis(["周一", "周二", "周三", "周四", "周五", "周六", "周日"])
    .add_yaxis("销量", [120, 200, 150, 80, 70, 110, 130])
    .set_global_opts(title_opts=opts.TitleOpts(title="特效散点图示例"))
)
```

### Map - 地图

```python
from pyecharts import options as opts
from pyecharts.charts import Map

map_chart = (
    Map()
    .add(
        "数据",
        [("广东省", 100), ("北京市", 50), ("上海市", 60), ("江西省", 40)],
        "china",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="地图示例"))
)
```

### Geo - 地理坐标系

```python
from pyecharts import options as opts
from pyecharts.charts import Geo

geo = (
    Geo()
    .add_schema(maptype="china")
    .add(
        "geo",
        [("北京", 100), ("上海", 80), ("广州", 60), ("深圳", 50)],
        type_="effectScatter",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="地理图示例"))
)
```

### Graph - 关系图

```python
from pyecharts import options as opts
from pyecharts.charts import Graph

nodes = [
    {"name": "节点 1"},
    {"name": "节点 2"},
    {"name": "节点 3"},
]
links = [
    {"source": "节点 1", "target": "节点 2"},
    {"source": "节点 2", "target": "节点 3"},
]

graph = (
    Graph()
    .add("", nodes, links, repulsion=8000)
    .set_global_opts(title_opts=opts.TitleOpts(title="关系图示例"))
)
```

### HeatMap - 热力图

```python
from pyecharts import options as opts
from pyecharts.charts import HeatMap

heatmap = (
    HeatMap()
    .add_xaxis(["周一", "周二", "周三", "周四", "周五", "周六", "周日"])
    .add_yaxis(
        "时间",
        ["12a", "1a", "2a", "3a", "4a", "5a", "6a", "7a", "8a", "9a"],
        [[0, 0, 10], [0, 1, 20], [1, 0, 30]],  # [x 索引，y 索引，值]
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="热力图示例"))
)
```

### Boxplot - 箱形图

```python
from pyecharts import options as opts
from pyecharts.charts import Boxplot

boxplot = (
    Boxplot()
    .add_xaxis(["类别 A", "类别 B", "类别 C"])
    .add_yaxis(
        "数据",
        [[10, 20, 30, 40, 50], [15, 25, 35, 45, 55], [12, 22, 32, 42, 52]],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="箱形图示例"))
)
```

### Kline - K 线图（蜡烛图）

```python
from pyecharts import options as opts
from pyecharts.charts import Kline

kline = (
    Kline()
    .add_xaxis(["2024-01-01", "2024-01-02", "2024-01-03"])
    .add_yaxis(
        "K 线",
        [[2320.26, 2320.26, 2287.3, 2362.94], [2300, 2291.3, 2288.26, 2308.38]],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="K 线图示例"))
)
```

### Gauge - 仪表盘

```python
from pyecharts import options as opts
from pyecharts.charts import Gauge

gauge = (
    Gauge()
    .add("", [("完成率", 75)])
    .set_global_opts(title_opts=opts.TitleOpts(title="仪表盘示例"))
)
```

### Funnel - 漏斗图

```python
from pyecharts import options as opts
from pyecharts.charts import Funnel

funnel = (
    Funnel()
    .add(
        "转化",
        [("访问", 100), ("咨询", 60), ("订单", 40), ("支付", 20)],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="漏斗图示例"))
)
```

### Radar - 雷达图

```python
from pyecharts import options as opts
from pyecharts.charts import Radar

radar = (
    Radar()
    .add_schema(
        schema=[
            {"name": "销售", "max": 100},
            {"name": "管理", "max": 100},
            {"name": "技术", "max": 100},
            {"name": "服务", "max": 100},
        ]
    )
    .add("预算", [[80, 70, 90, 85]])
    .add("实际", [[70, 80, 85, 90]])
    .set_global_opts(title_opts=opts.TitleOpts(title="雷达图示例"))
)
```

### Polar - 极坐标图

```python
from pyecharts import options as opts
from pyecharts.charts import Polar

polar = (
    Polar()
    .add_schema(angleaxis_opts=opts.AngleAxisOpts(data=["周一", "周二", "周三"]))
    .add("数据", [1, 2, 3], type_="bar")
    .set_global_opts(title_opts=opts.TitleOpts(title="极坐标图示例"))
)
```

### WordCloud - 词云图

```python
from pyecharts import options as opts
from pyecharts.charts import WordCloud

wordcloud = (
    WordCloud()
    .add(
        words=[("Python", 100), ("ECharts", 80), ("可视化", 60)],
        word_size_range=[20, 50],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="词云图示例"))
)
```

### Liquid - 水球图

```python
from pyecharts import options as opts
from pyecharts.charts import Liquid

liquid = (
    Liquid()
    .add("lq", [0.6, 0.7])
    .set_global_opts(title_opts=opts.TitleOpts(title="水球图示例"))
)
```

### Sunburst - 旭日图

```python
from pyecharts import options as opts
from pyecharts.charts import Sunburst

sunburst = (
    Sunburst()
    .add(
        "数据",
        [
            {"name": "大类 A", "value": 10, "children": [{"name": "子类 A1", "value": 5}]},
            {"name": "大类 B", "value": 8},
        ],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="旭日图示例"))
)
```

### Tree - 树图

```python
from pyecharts import options as opts
from pyecharts.charts import Tree

tree = (
    Tree()
    .add(
        "tree",
        [
            {"name": "根节点", "children": [{"name": "子节点 1"}, {"name": "子节点 2"}]},
        ],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="树图示例"))
)
```

### TreeMap - 矩形树图

```python
from pyecharts import options as opts
from pyecharts.charts import TreeMap

treemap = (
    TreeMap()
    .add(
        "数据",
        [
            {"name": "类别 A", "value": 100},
            {"name": "类别 B", "value": 80},
            {"name": "类别 C", "value": 60},
        ],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="矩形树图示例"))
)
```

### ThemeRiver - 主题河流图

```python
from pyecharts import options as opts
from pyecharts.charts import ThemeRiver

theme_river = (
    ThemeRiver()
    .add(
        ["主题 A", "主题 B", "主题 C"],
        [["2024-01", 10, 20], ["2024-02", 15, 25]],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="主题河流图示例"))
)
```

### Sankey - 桑基图

```python
from pyecharts import options as opts
from pyecharts.charts import Sankey

sankey = (
    Sankey()
    .add(
        "sankey",
        nodes=[{"name": "来源"}, {"name": "中间"}, {"name": "目标"}],
        links=[
            {"source": "来源", "target": "中间", "value": 50},
            {"source": "中间", "target": "目标", "value": 30},
        ],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="桑基图示例"))
)
```

### Chord - 和弦图

```python
from pyecharts import options as opts
from pyecharts.charts import Chord

chord = (
    Chord()
    .add(
        schema=[
            {"name": "A"},
            {"name": "B"},
            {"name": "C"},
        ],
        matrix=[[0, 10, 20], [10, 0, 30], [20, 30, 0]],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="和弦图示例"))
)
```

### Parallel - 平行坐标系

```python
from pyecharts import options as opts
from pyecharts.charts import Parallel

parallel = (
    Parallel()
    .add_schema(
        schema=[
            {"dim": 0, "name": "维度 1"},
            {"dim": 1, "name": "维度 2"},
            {"dim": 2, "name": "维度 3"},
        ]
    )
    .add("数据", [[1, 2, 3], [2, 3, 4]])
    .set_global_opts(title_opts=opts.TitleOpts(title="平行坐标图示例"))
)
```

### PictorialBar - 象形柱图

```python
from pyecharts import options as opts
from pyecharts.charts import PictorialBar

pictorial_bar = (
    PictorialBar()
    .add_xaxis(["A", "B", "C"])
    .add_yaxis("数据", [10, 20, 30], symbol="circle")
    .set_global_opts(title_opts=opts.TitleOpts(title="象形柱图示例"))
)
```

### Calendar - 日历图

```python
from pyecharts import options as opts
from pyecharts.charts import Calendar

calendar = (
    Calendar()
    .add(
        "",
        [["2024-01-01", 10], ["2024-01-02", 20]],
        calendar_opts=opts.CalendarOpts(range_="2024"),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="日历图示例"))
)
```

### Custom - 自定义图表

```python
from pyecharts import options as opts
from pyecharts.charts import Custom

custom = (
    Custom()
    .add_xaxis(["A", "B", "C"])
    .add_yaxis(
        "数据",
        [[10, 20], [20, 30], [30, 40]],
        custom_series_func="function (api) { return {...}; }",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="自定义图表示例"))
)
```

### Violin - 小提琴图 (Echarts 6 新增)

```python
from pyecharts import options as opts
from pyecharts.charts import Custom

# 小提琴图使用 custom 系列实现
violin = (
    Custom()
    .add_xaxis(["类别 A", "类别 B", "类别 C"])
    .add_yaxis(
        "小提琴",
        [[0, 10, 20, 30, 40, 50], [5, 15, 25, 35, 45, 55]],
        custom_series_type="violin",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="小提琴图示例"))
)
```

### Stage - 阶段图 (Echarts 6 新增)

```python
from pyecharts import options as opts
from pyecharts.charts import Custom

stage = (
    Custom()
    .add_xaxis(["阶段 1", "阶段 2", "阶段 3"])
    .add_yaxis(
        "阶段",
        [[10, 20], [20, 30], [30, 40]],
        custom_series_type="stage",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="阶段图示例"))
)
```

### SegmentedDoughnut - 分段环形图 (Echarts 6 新增)

```python
from pyecharts import options as opts
from pyecharts.charts import Custom

doughnut = (
    Custom()
    .add(
        "环形图",
        [{"name": "A", "value": 30}, {"name": "B", "value": 40}],
        custom_series_type="segmentedDoughnut",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="分段环形图示例"))
)
```

### Contour - 等高线图 (Echarts 6 新增)

```python
from pyecharts import options as opts
from pyecharts.charts import Custom

contour = (
    Custom()
    .add_xaxis([i for i in range(10)])
    .add_yaxis(
        "等高线",
        [[x, y, (x**2 + y**2)**0.5] for x in range(10) for y in range(10)],
        custom_series_type="contour",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="等高线图示例"))
)
```

### BarRange - 范围柱状图 (Echarts 6 新增)

```python
from pyecharts import options as opts
from pyecharts.charts import Custom

bar_range = (
    Custom()
    .add_xaxis(["类别 A", "类别 B", "类别 C"])
    .add_yaxis(
        "范围",
        [[10, 30], [20, 40], [15, 35]],  # [最小值，最大值]
        custom_series_type="barRange",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="范围柱状图示例"))
)
```

### LineRange - 范围折线图 (Echarts 6 新增)

```python
from pyecharts import options as opts
from pyecharts.charts import Custom

line_range = (
    Custom()
    .add_xaxis(["周一", "周二", "周三", "周四", "周五"])
    .add_yaxis(
        "范围",
        [[10, 30], [15, 35], [20, 40], [18, 38], [12, 32]],
        custom_series_type="lineRange",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="范围折线图示例"))
)
```

### BMap - 百度地图

```python
from pyecharts import options as opts
from pyecharts.charts import BMap

bmap = (
    BMap()
    .add_schema(baidu_ak="your_baidu_ak", center=[116.40, 39.90], zoom=10)
    .add("数据", [("天安门", [116.40, 39.90])])
    .set_global_opts(title_opts=opts.TitleOpts(title="百度地图示例"))
)
```

### AMap - 高德地图

```python
from pyecharts import options as opts
from pyecharts.charts import AMap

amap = (
    AMap()
    .add_schema(amap_ak="your_amap_ak", center=[116.40, 39.90], zoom=10)
    .add("数据", [("天安门", [116.40, 39.90])])
    .set_global_opts(title_opts=opts.TitleOpts(title="高德地图示例"))
)
```

### GMap - GMap 地图

```python
from pyecharts import options as opts
from pyecharts.charts import GMap

gmap = (
    GMap()
    .add("数据", [("China", 100), ("USA", 80)], "world")
    .set_global_opts(title_opts=opts.TitleOpts(title="GMap 示例"))
)
```

### LMap - Leaflet 地图

```python
from pyecharts import options as opts
from pyecharts.charts import LMap

lmap = (
    LMap()
    .add("数据", [("Beijing", [39.90, 116.40])])
    .set_global_opts(title_opts=opts.TitleOpts(title="Leaflet 地图示例"))
)
```

---

## 复合图表

### Grid - 直角坐标系多图表

```python
from pyecharts import options as opts
from pyecharts.charts import Grid, Bar, Line

bar = Bar().add_xaxis(["A", "B"]).add_yaxis("bar", [10, 20])
line = Line().add_xaxis(["A", "B"]).add_yaxis("line", [5, 15])

grid = (
    Grid()
    .add(bar, grid_opts=opts.GridOpts(pos_left="5%", pos_right="55%"))
    .add(line, grid_opts=opts.GridOpts(pos_left="50%", pos_right="5%"))
    .set_global_opts(title_opts=opts.TitleOpts(title="Grid 组合图示例"))
)
```

### Page - 顺序多图表

```python
from pyecharts import options as opts
from pyecharts.charts import Page, Bar, Line

bar = Bar().add_xaxis(["A"]).add_yaxis("bar", [10])
line = Line().add_xaxis(["A"]).add_yaxis("line", [5])

page = (
    Page(layout=page.SimplePageLayout())
    .add(bar)
    .add(line)
)
```

### Tab - 标签页多图表

```python
from pyecharts import options as opts
from pyecharts.charts import Tab, Bar, Line

bar = Bar().add_xaxis(["A"]).add_yaxis("bar", [10])
line = Line().add_xaxis(["A"]).add_yaxis("line", [5])

tab = Tab()
tab.add(bar, "柱状图")
tab.add(line, "折线图")
```

### Timeline - 时间线轮播图

```python
from pyecharts import options as opts
from pyecharts.charts import Timeline, Bar

timeline = Timeline()
for i in range(2014, 2018):
    bar = Bar().add_xaxis(["A", "B"]).add_yaxis("data", [10, 20])
    timeline.add(bar, f"{i} 年")
```

---

## 3D 图表

### Bar3D - 3D 柱状图

```python
from pyecharts import options as opts
from pyecharts.charts import Bar3D

bar3d = (
    Bar3D()
    .add(
        "3D 柱状",
        [[x, y, z] for x in range(10) for y in range(10) for z in range(5)],
        xaxis3d_opts=opts.Axis3DOpts(type_="category"),
        yaxis3d_opts=opts.Axis3DOpts(type_="category"),
        grid3d_opts=opts.Grid3DOpts(width=100, height=100, depth=100),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="3D 柱状图示例"))
)
```

### Line3D - 3D 折线图

```python
from pyecharts import options as opts
from pyecharts.charts import Line3D
import math

data = [[math.sin(t / 10), math.cos(t / 10), t / 10] for t in range(0, 100)]

line3d = (
    Line3D()
    .add(
        "",
        data,
        line3d_opts=opts.Line3DOpts(magnitude=3),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="3D 折线图示例"))
)
```

### Scatter3D - 3D 散点图

```python
from pyecharts import options as opts
from pyecharts.charts import Scatter3D
import random

data = [[random.randint(0, 100), random.randint(0, 100), random.randint(0, 100)] for _ in range(80)]

scatter3d = (
    Scatter3D()
    .add("", data)
    .set_global_opts(title_opts=opts.TitleOpts(title="3D 散点图示例"))
)
```

### Surface3D - 3D 曲面图

```python
from pyecharts import options as opts
from pyecharts.charts import Surface3D
import math

data = [[x, y, math.sin(x) * math.cos(y)] for x in range(-5, 5) for y in range(-5, 5)]

surface3d = (
    Surface3D()
    .add("", data)
    .set_global_opts(title_opts=opts.TitleOpts(title="3D 曲面图示例"))
)
```

### Lines3D - 3D 轨迹线

```python
from pyecharts import options as opts
from pyecharts.charts import Lines3D

lines3d = (
    Lines3D()
    .add(
        "轨迹",
        [[[x, x**2, 0] for x in range(-5, 5)]],
        line3d_opts=opts.Lines3DEffectOpts(),
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="3D 轨迹线图示例"))
)
```

### Map3D - 3D 地图

```python
from pyecharts import options as opts
from pyecharts.charts import Map3D

map3d = (
    Map3D()
    .add_schema()
    .add(
        "数据",
        [("广东省", 100), ("北京市", 50)],
        type_="bars3D",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="3D 地图示例"))
)
```

### MapGlobe - 地球

```python
from pyecharts import options as opts
from pyecharts.charts import MapGlobe

map_globe = (
    MapGlobe()
    .add_schema()
    .add(
        "数据",
        [("China", 100), ("United States", 80)],
        type_="bars3D",
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="地球示例"))
)
```

### GraphGL - 3D 关系图

```python
from pyecharts import options as opts
from pyecharts.charts import GraphGL

graph_gl = (
    GraphGL()
    .add(
        "",
        nodes=[{"name": "节点 1", "value": 10}],
        links=[{"source": "节点 1", "target": "节点 2"}],
    )
    .set_global_opts(title_opts=opts.TitleOpts(title="3D 关系图示例"))
)
```
