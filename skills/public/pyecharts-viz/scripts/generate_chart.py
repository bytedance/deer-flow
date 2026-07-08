#!/usr/bin/env python3
"""
pyecharts 图表生成器 - 用于生成各种图表类型的示例

使用方法:
    python generate_chart.py [chart_type] [output_file]

示例:
    python generate_chart.py bar output.html
    python generate_chart.py line line_chart.html
"""

import sys
import random
import math
from pyecharts import options as opts
from pyecharts.charts import (
    Bar, Line, Pie, Scatter, Map, Geo, Graph, HeatMap,
    Boxplot, Kline, Gauge, Funnel, Radar, Polar,
    WordCloud, Liquid, Sunburst, Tree, TreeMap,
    ThemeRiver, Sankey, Chord, Parallel, PictorialBar,
    Calendar, Grid, Page, Tab, Timeline, EffectScatter,
    Bar3D, Line3D, Scatter3D, Surface3D, Map3D, MapGlobe,
    GraphGL, Lines3D, GMap, LMap, BMap, AMap, Custom
)
from pyecharts.faker import Faker


# ==================== 基础图表 ====================

def create_bar(output="bar_chart.html"):
    """创建柱状图"""
    bar = (
        Bar()
        .add_xaxis(Faker.clothes)
        .add_yaxis("商家 A", Faker.values())
        .add_yaxis("商家 B", Faker.values())
        .set_global_opts(title_opts=opts.TitleOpts(title="柱状图示例"))
    )
    bar.render(output)
    print(f"柱状图已生成：{output}")


def create_line(output="line_chart.html"):
    """创建折线图"""
    line = (
        Line()
        .add_xaxis(Faker.week)
        .add_yaxis("销售额", Faker.values())
        .set_global_opts(title_opts=opts.TitleOpts(title="折线图示例"))
    )
    line.render(output)
    print(f"折线图已生成：{output}")


def create_pie(output="pie_chart.html"):
    """创建饼图"""
    pie = (
        Pie()
        .add("商品", list(zip(Faker.clothes, Faker.values())), radius=["40%", "75%"])
        .set_global_opts(title_opts=opts.TitleOpts(title="饼图示例"))
    )
    pie.render(output)
    print(f"饼图已生成：{output}")


def create_scatter(output="scatter_chart.html"):
    """创建散点图"""
    scatter = (
        Scatter()
        .add_xaxis(Faker.week)
        .add_yaxis("销量", Faker.values())
        .set_global_opts(title_opts=opts.TitleOpts(title="散点图示例"))
    )
    scatter.render(output)
    print(f"散点图已生成：{output}")


def create_effectscatter(output="effectscatter_chart.html"):
    """创建特效散点图"""
    es = (
        EffectScatter()
        .add_xaxis(Faker.week)
        .add_yaxis("销量", Faker.values())
        .set_global_opts(title_opts=opts.TitleOpts(title="特效散点图示例"))
    )
    es.render(output)
    print(f"特效散点图已生成：{output}")


def create_map(output="map_chart.html"):
    """创建地图"""
    map_chart = (
        Map()
        .add("数据", [("广东省", 100), ("北京市", 50), ("上海市", 60), ("江西省", 40)], "china")
        .set_global_opts(title_opts=opts.TitleOpts(title="地图示例"))
    )
    map_chart.render(output)
    print(f"地图已生成：{output}")


def create_geo(output="geo_chart.html"):
    """创建地理坐标图"""
    geo = (
        Geo()
        .add_schema(maptype="china")
        .add("geo", [("北京", 100), ("上海", 80), ("广州", 60), ("深圳", 50)], type_="effectScatter")
        .set_global_opts(title_opts=opts.TitleOpts(title="地理图示例"))
    )
    geo.render(output)
    print(f"地理图已生成：{output}")


def create_graph(output="graph_chart.html"):
    """创建关系图"""
    nodes = [{"name": "节点 1"}, {"name": "节点 2"}, {"name": "节点 3"}]
    links = [
        {"source": "节点 1", "target": "节点 2"},
        {"source": "节点 2", "target": "节点 3"},
    ]
    graph = Graph().add("", nodes, links, repulsion=8000)
    graph.set_global_opts(title_opts=opts.TitleOpts(title="关系图示例"))
    graph.render(output)
    print(f"关系图已生成：{output}")


def create_heatmap(output="heatmap_chart.html"):
    """创建热力图"""
    data = [[i, j, random.randint(0, 100)] for i in range(7) for j in range(10)]
    heatmap = (
        HeatMap()
        .add_xaxis(Faker.week)
        .add_yaxis("时间", Faker.clock)
        .add_series("热力", data)
        .set_global_opts(title_opts=opts.TitleOpts(title="热力图示例"))
    )
    heatmap.render(output)
    print(f"热力图已生成：{output}")


def create_boxplot(output="boxplot_chart.html"):
    """创建箱形图"""
    data = [
        [random.randint(1, 100) for _ in range(6)] for _ in range(3)
    ]
    boxplot = (
        Boxplot()
        .add_xaxis(["类别 A", "类别 B", "类别 C"])
        .add_yaxis("数据", data)
        .set_global_opts(title_opts=opts.TitleOpts(title="箱形图示例"))
    )
    boxplot.render(output)
    print(f"箱形图已生成：{output}")


def create_kline(output="kline_chart.html"):
    """创建 K 线图"""
    data = [
        [2320.26, 2320.26, 2287.3, 2362.94],
        [2300, 2291.3, 2288.26, 2308.38],
        [2320.26, 2320.26, 2287.3, 2362.94],
    ]
    kline = (
        Kline()
        .add_xaxis(["2024-01-01", "2024-01-02", "2024-01-03"])
        .add_yaxis("K 线", data)
        .set_global_opts(title_opts=opts.TitleOpts(title="K 线图示例"))
    )
    kline.render(output)
    print(f"K 线图已生成：{output}")


def create_gauge(output="gauge_chart.html"):
    """创建仪表盘"""
    gauge = (
        Gauge()
        .add("完成率", [("percentage", 75)])
        .set_global_opts(title_opts=opts.TitleOpts(title="仪表盘示例"))
    )
    gauge.render(output)
    print(f"仪表盘已生成：{output}")


def create_funnel(output="funnel_chart.html"):
    """创建漏斗图"""
    funnel = (
        Funnel()
        .add("转化", [("访问", 100), ("咨询", 60), ("订单", 40), ("支付", 20)])
        .set_global_opts(title_opts=opts.TitleOpts(title="漏斗图示例"))
    )
    funnel.render(output)
    print(f"漏斗图已生成：{output}")


def create_radar(output="radar_chart.html"):
    """创建雷达图"""
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
    radar.render(output)
    print(f"雷达图已生成：{output}")


def create_polar(output="polar_chart.html"):
    """创建极坐标图"""
    polar = (
        Polar()
        .add_schema(angleaxis_opts=opts.AngleAxisOpts(data=["周一", "周二", "周三"]))
        .add("数据", [1, 2, 3], type_="bar")
        .set_global_opts(title_opts=opts.TitleOpts(title="极坐标图示例"))
    )
    polar.render(output)
    print(f"极坐标图已生成：{output}")


def create_wordcloud(output="wordcloud_chart.html"):
    """创建词云图"""
    wordcloud = (
        WordCloud()
        .add(words=[("Python", 100), ("ECharts", 80), ("可视化", 60)], word_size_range=[20, 50])
        .set_global_opts(title_opts=opts.TitleOpts(title="词云图示例"))
    )
    wordcloud.render(output)
    print(f"词云图已生成：{output}")


def create_liquid(output="liquid_chart.html"):
    """创建水球图"""
    liquid = (
        Liquid()
        .add("lq", [0.6, 0.7])
        .set_global_opts(title_opts=opts.TitleOpts(title="水球图示例"))
    )
    liquid.render(output)
    print(f"水球图已生成：{output}")


def create_sunburst(output="sunburst_chart.html"):
    """创建旭日图"""
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
    sunburst.render(output)
    print(f"旭日图已生成：{output}")


def create_tree(output="tree_chart.html"):
    """创建树图"""
    tree = (
        Tree()
        .add(
            "tree",
            [{"name": "根节点", "children": [{"name": "子节点 1"}, {"name": "子节点 2"}]}],
        )
        .set_global_opts(title_opts=opts.TitleOpts(title="树图示例"))
    )
    tree.render(output)
    print(f"树图已生成：{output}")


def create_treemap(output="treemap_chart.html"):
    """创建矩形树图"""
    treemap = (
        TreeMap()
        .add("数据", [{"name": "类别 A", "value": 100}, {"name": "类别 B", "value": 80}, {"name": "类别 C", "value": 60}])
        .set_global_opts(title_opts=opts.TitleOpts(title="矩形树图示例"))
    )
    treemap.render(output)
    print(f"矩形树图已生成：{output}")


def create_themeriver(output="themeriver_chart.html"):
    """创建主题河流图"""
    theme_river = (
        ThemeRiver()
        .add(["主题 A", "主题 B", "主题 C"], [["2024-01", 10, 20], ["2024-02", 15, 25]])
        .set_global_opts(title_opts=opts.TitleOpts(title="主题河流图示例"))
    )
    theme_river.render(output)
    print(f"主题河流图已生成：{output}")


def create_sankey(output="sankey_chart.html"):
    """创建桑基图"""
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
    sankey.render(output)
    print(f"桑基图已生成：{output}")


def create_chord(output="chord_chart.html"):
    """创建和弦图"""
    chord = (
        Chord()
        .add(
            schema=[{"name": "A"}, {"name": "B"}, {"name": "C"}],
            matrix=[[0, 10, 20], [10, 0, 30], [20, 30, 0]],
        )
        .set_global_opts(title_opts=opts.TitleOpts(title="和弦图示例"))
    )
    chord.render(output)
    print(f"和弦图已生成：{output}")


def create_parallel(output="parallel_chart.html"):
    """创建平行坐标图"""
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
    parallel.render(output)
    print(f"平行坐标图已生成：{output}")


def create_pictorialbar(output="pictorialbar_chart.html"):
    """创建象形柱图"""
    pictorial_bar = (
        PictorialBar()
        .add_xaxis(["A", "B", "C"])
        .add_yaxis("数据", [10, 20, 30], symbol="circle")
        .set_global_opts(title_opts=opts.TitleOpts(title="象形柱图示例"))
    )
    pictorial_bar.render(output)
    print(f"象形柱图已生成：{output}")


def create_calendar(output="calendar_chart.html"):
    """创建日历图"""
    calendar = (
        Calendar()
        .add("", [["2024-01-01", 10], ["2024-01-02", 20]], calendar_opts=opts.CalendarOpts(range_="2024"))
        .set_global_opts(title_opts=opts.TitleOpts(title="日历图示例"))
    )
    calendar.render(output)
    print(f"日历图已生成：{output}")


# ==================== 复合图表 ====================

def create_grid(output="grid_chart.html"):
    """创建组合图表"""
    bar = Bar().add_xaxis(Faker.clothes).add_yaxis("柱状", Faker.values())
    line = Line().add_xaxis(Faker.clothes).add_yaxis("折线", Faker.values())

    grid = (
        Grid()
        .add(bar, grid_opts=opts.GridOpts(pos_left="5%", pos_right="55%"))
        .add(line, grid_opts=opts.GridOpts(pos_left="50%", pos_right="5%"))
        .set_global_opts(title_opts=opts.TitleOpts(title="Grid 组合图示例"))
    )
    grid.render(output)
    print(f"组合图已生成：{output}")


def create_page(output="page_chart.html"):
    """创建顺序多图表"""
    bar = Bar().add_xaxis(Faker.clothes).add_yaxis("柱状", Faker.values())
    line = Line().add_xaxis(Faker.clothes).add_yaxis("折线", Faker.values())

    page = Page(layout=page.SimplePageLayout()).add(bar).add(line)
    page.render(output)
    print(f"顺序图表已生成：{output}")


def create_tab(output="tab_chart.html"):
    """创建标签页多图表"""
    bar = Bar().add_xaxis(Faker.clothes).add_yaxis("柱状", Faker.values())
    line = Line().add_xaxis(Faker.clothes).add_yaxis("折线", Faker.values())

    tab = Tab()
    tab.add(bar, "柱状图")
    tab.add(line, "折线图")
    tab.render(output)
    print(f"标签图表已生成：{output}")


def create_timeline(output="timeline_chart.html"):
    """创建时间线轮播图"""
    timeline = Timeline()
    for year in range(2020, 2024):
        bar = (
            Bar()
            .add_xaxis(Faker.clothes)
            .add_yaxis("商家 A", Faker.values())
            .set_global_opts(title_opts=opts.TitleOpts(title=f"{year}年销售数据"))
        )
        timeline.add(bar, f"{year}年")
    timeline.render(output)
    print(f"时间线图已生成：{output}")


# ==================== 3D 图表 ====================

def create_bar3d(output="bar3d_chart.html"):
    """创建 3D 柱状图"""
    data = [[i, j, random.randint(0, 10)] for i in range(10) for j in range(10)]

    bar3d = (
        Bar3D()
        .add(
            "3D 柱状",
            data,
            xaxis3d_opts=opts.Axis3DOpts(type_="category"),
            yaxis3d_opts=opts.Axis3DOpts(type_="category"),
            grid3d_opts=opts.Grid3DOpts(width=100, height=100, depth=100),
        )
        .set_global_opts(title_opts=opts.TitleOpts(title="3D 柱状图示例"))
    )
    bar3d.render(output)
    print(f"3D 柱状图已生成：{output}")


def create_line3d(output="line3d_chart.html"):
    """创建 3D 折线图"""
    data = [[math.sin(t / 10), math.cos(t / 10), t / 10] for t in range(0, 100)]

    line3d = (
        Line3D().add("", data, line3d_opts=opts.Line3DOpts(magnitude=3)).set_global_opts(
            title_opts=opts.TitleOpts(title="3D 折线图示例")
        )
    )
    line3d.render(output)
    print(f"3D 折线图已生成：{output}")


def create_scatter3d(output="scatter3d_chart.html"):
    """创建 3D 散点图"""
    data = [
        [random.randint(0, 100), random.randint(0, 100), random.randint(0, 100)] for _ in range(80)
    ]

    scatter3d = Scatter3D().add("", data).set_global_opts(
        title_opts=opts.TitleOpts(title="3D 散点图示例")
    )
    scatter3d.render(output)
    print(f"3D 散点图已生成：{output}")


def create_surface3d(output="surface3d_chart.html"):
    """创建 3D 曲面图"""
    data = [[x, y, math.sin(x) * math.cos(y)] for x in range(-5, 5) for y in range(-5, 5)]

    surface3d = Surface3D().add("", data).set_global_opts(
        title_opts=opts.TitleOpts(title="3D 曲面图示例")
    )
    surface3d.render(output)
    print(f"3D 曲面图已生成：{output}")


def create_lines3d(output="lines3d_chart.html"):
    """创建 3D 轨迹线"""
    lines3d = (
        Lines3D()
        .add("轨迹", [[[x, x**2, 0] for x in range(-5, 5)]], line3d_opts=opts.Lines3DEffectOpts())
        .set_global_opts(title_opts=opts.TitleOpts(title="3D 轨迹线图示例"))
    )
    lines3d.render(output)
    print(f"3D 轨迹线图已生成：{output}")


def create_map3d(output="map3d_chart.html"):
    """创建 3D 地图"""
    map3d = (
        Map3D()
        .add_schema()
        .add("数据", [("广东省", 100), ("北京市", 50)], type_="bars3D")
        .set_global_opts(title_opts=opts.TitleOpts(title="3D 地图示例"))
    )
    map3d.render(output)
    print(f"3D 地图已生成：{output}")


def create_mapglobe(output="mapglobe_chart.html"):
    """创建地球"""
    map_globe = (
        MapGlobe()
        .add_schema()
        .add("数据", [("China", 100), ("United States", 80)], type_="bars3D")
        .set_global_opts(title_opts=opts.TitleOpts(title="地球示例"))
    )
    map_globe.render(output)
    print(f"地球已生成：{output}")


def create_graphgl(output="graphgl_chart.html"):
    """创建 3D 关系图"""
    graph_gl = (
        GraphGL()
        .add(
            "",
            nodes=[{"name": "节点 1", "value": 10}],
            links=[{"source": "节点 1", "target": "节点 2"}],
        )
        .set_global_opts(title_opts=opts.TitleOpts(title="3D 关系图示例"))
    )
    graph_gl.render(output)
    print(f"3D 关系图已生成：{output}")


# ==================== 地图系列 ====================

def create_bmap(output="bmap_chart.html"):
    """创建百度地图"""
    bmap = (
        BMap()
        .add_schema(baidu_ak="YOUR_BAIDU_AK", center=[116.40, 39.90], zoom=10)
        .add("数据", [("天安门", [116.40, 39.90])])
        .set_global_opts(title_opts=opts.TitleOpts(title="百度地图示例"))
    )
    bmap.render(output)
    print(f"百度地图已生成：{output}")


def create_amap(output="amap_chart.html"):
    """创建高德地图"""
    amap = (
        AMap()
        .add_schema(amap_ak="YOUR_AMAP_AK", center=[116.40, 39.90], zoom=10)
        .add("数据", [("天安门", [116.40, 39.90])])
        .set_global_opts(title_opts=opts.TitleOpts(title="高德地图示例"))
    )
    amap.render(output)
    print(f"高德地图已生成：{output}")


def create_gmap(output="gmap_chart.html"):
    """创建 GMap 地图"""
    gmap = (
        GMap()
        .add("数据", [("China", 100), ("USA", 80)], "world")
        .set_global_opts(title_opts=opts.TitleOpts(title="GMap 示例"))
    )
    gmap.render(output)
    print(f"GMap 已生成：{output}")


def create_lmap(output="lmap_chart.html"):
    """创建 Leaflet 地图"""
    lmap = (
        LMap()
        .add("数据", [("Beijing", [39.90, 116.40])])
        .set_global_opts(title_opts=opts.TitleOpts(title="Leaflet 地图示例"))
    )
    lmap.render(output)
    print(f"Leaflet 地图已生成：{output}")


# ==================== 自定义图表 (Echarts 6) ====================

def create_custom(output="custom_chart.html"):
    """创建自定义图表"""
    custom = (
        Custom()
        .add_xaxis(["A", "B", "C"])
        .add_yaxis("数据", [[10, 20], [20, 30], [30, 40]])
        .set_global_opts(title_opts=opts.TitleOpts(title="自定义图表示例"))
    )
    custom.render(output)
    print(f"自定义图表已生成：{output}")


def main():
    chart_funcs = {
        # 基础图表
        "bar": create_bar,
        "line": create_line,
        "pie": create_pie,
        "scatter": create_scatter,
        "effectscatter": create_effectscatter,
        "map": create_map,
        "geo": create_geo,
        "graph": create_graph,
        "heatmap": create_heatmap,
        "boxplot": create_boxplot,
        "kline": create_kline,
        "gauge": create_gauge,
        "funnel": create_funnel,
        "radar": create_radar,
        "polar": create_polar,
        "wordcloud": create_wordcloud,
        "liquid": create_liquid,
        "sunburst": create_sunburst,
        "tree": create_tree,
        "treemap": create_treemap,
        "themeriver": create_themeriver,
        "sankey": create_sankey,
        "chord": create_chord,
        "parallel": create_parallel,
        "pictorialbar": create_pictorialbar,
        "calendar": create_calendar,
        "custom": create_custom,
        # 复合图表
        "grid": create_grid,
        "page": create_page,
        "tab": create_tab,
        "timeline": create_timeline,
        # 3D 图表
        "bar3d": create_bar3d,
        "line3d": create_line3d,
        "scatter3d": create_scatter3d,
        "surface3d": create_surface3d,
        "lines3d": create_lines3d,
        "map3d": create_map3d,
        "mapglobe": create_mapglobe,
        "graphgl": create_graphgl,
        # 地图系列
        "bmap": create_bmap,
        "amap": create_amap,
        "gmap": create_gmap,
        "lmap": create_lmap,
    }

    if len(sys.argv) < 2:
        print(__doc__)
        print("\n支持的图表类型:")
        for name in sorted(chart_funcs.keys()):
            print(f"  - {name}")
        return

    chart_type = sys.argv[1].lower()
    output = sys.argv[2] if len(sys.argv) > 2 else f"{chart_type}_chart.html"

    if chart_type in chart_funcs:
        chart_funcs[chart_type](output)
    else:
        print(f"不支持的图表类型：{chart_type}")
        print("\n支持的图表类型:")
        for name in sorted(chart_funcs.keys()):
            print(f"  - {name}")
        sys.exit(1)


if __name__ == "__main__":
    main()
