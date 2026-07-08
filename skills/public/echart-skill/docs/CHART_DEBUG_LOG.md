# ECharts 图表生成 — 调试记录 & 防错准则

> 每次发现并修复一个图表 bug，必须记录在此。后续开发必须对照此文档，避免重复犯错。

## 铁律

1. **ECharts `encode` + `dataset` 只适用于 bar/line/scatter(cartesian)/candlestick/boxplot。其他类型必须用 `series.data` 直接数组。**
2. **Map 必须同时有 `series.data` + `visualMap`，缺一不可。**
3. **3D 图表（bar3D/scatter3D/surface/line3D）必须内联 `echarts-gl.min.js`。**
4. **Scatter bubble 的大小控制用 `encode.z` + `visualMap {inRange: {symbolSize: [min, max]}}`，不用字符串 `symbolSize`。**
5. **Geo scatter 的 `data` 格式：`{name, value: [lng, lat, val]}`，`encode` 用数值索引 `{lng:0, lat:1, value:2}`。**
6. **Radar 的 `data` 格式：`{name, value: [dim1, dim2, dim3, dim4]}`，value 是数组不是单个值。**
7. **Pie/Funnel 的 `data` 格式：`{name, value: single_number}`，用 `series.data` 不用 dataset。**
8. **JSON 序列化前必须把 date/datetime 列转为 string，用 `json.dumps(default=str)`。**
9. **所有图表必须显式设置 `tooltip: {}` + `toolbox: {saveAsImage, dataView}`。**
10. **每个图表生成后必须验证：`"type"` 存在、数据格式正确、无空 data。**

---

## 已修复 Bug 清单

### #1 — 图表空白（无 series type）
- **日期**：2026-06-13
- **现象**：所有 one-shot 图表（只传 `chart_type`，不传 `echarts_option`）输出空白
- **根因**：`generate_echarts_html` 只读 `config.echarts_option`，为空时 option=`{}`，ECharts 不知道渲染什么类型
- **修复**：新增 `_auto_build_option(chart_type, df)` 函数，根据 type + DataFrame 列名自动生成完整 option

### #2 — Line chart 日期 type 报错
- **日期**：2026-06-13
- **现象**：DuckDB DATE 列 → `json.dumps` 抛出 "Object of type date is not JSON serializable"
- **根因**：DuckDB 返回 Python `datetime.date`，JSON 不支持
- **修复**：在 `generate_echarts_html` 入口处，检测并转换所有 date/datetime 列为 string；所有 `json.dumps` 添加 `default=str`

### #3 — Map 无数据颜色
- **日期**：2026-06-13
- **现象**：地图能渲染但所有省份同一颜色，无数据区分
- **根因**：Map chart 需要 `visualMap` 组件才能将数据值映射为颜色
- **修复**：`_auto_build_option("map")` 自动添加 `visualMap: {min, max, inRange: {color: [...]}}`

### #4 — Map 省份名不匹配 GeoJSON
- **日期**：2026-06-13
- **现象**：数据中的省份名（如"北京市"）与 GeoJSON feature name（"北京"）不一致，数据绑定失败
- **根因**：数据保留全称，GeoJSON 使用简称
- **修复**：`normalize_map_name()` 在 map 数据注入前标准化省份名（北京市→北京）

### #5 — 3D 图表空白
- **日期**：2026-06-13
- **现象**：bar3D/scatter3D/surface/line3D/globe 全部空白
- **根因**：3D 图表需要 `echarts-gl.min.js`，但未嵌入 HTML
- **修复**：检测 series type 包含 3D 类型时，自动内联 echarts-gl.min.js

### #6 — Radar/Funnel/Pie 无数据
- **日期**：2026-06-13
- **现象**：这些类型的图表有结构但无数据
- **根因**：这些类型不支持 `dataset` + `encode`，数据必须放在 `series.data` 数组中
- **修复**：根据 `series.type` 判断数据注入方式，18 种类型改用 `series.data`

### #7 — Radar 数据只有单值
- **日期**：2026-06-13
- **现象**：雷达图 2 个系列各只有 1 个值，对应 4 个指标轴只显示第一个
- **根因**：数据注入时 `value: row[1]` 只取了第二列，没取剩余列
- **修复**：radar/parallel 类型 `value` 改为数组 `[row[1], row[2], row[3], row[4]]`

### #8 — Scatter Bubble 无数据
- **日期**：2026-06-13
- **现象**：气泡散点图空白
- **根因**：`symbolSize: "sz"` 是字符串，ECharts 不识别为维度引用。正确方式是 `encode.z` + `visualMap {inRange: {symbolSize: [min, max]}}`
- **修复**：自动转换字符串 symbolSize → encode.z，并自动添加 visualMap

### #9 — Scatter Bubble 所有点一样大
- **日期**：2026-06-13
- **现象**：`encode.z` 设置了但点大小无变化
- **根因**：`encode.z` 需要配合 `visualMap` 才能控制 symbolSize
- **修复**：检测到 `encode.z` 存在时自动添加 `visualMap: {inRange: {symbolSize: [5, 60]}}`

### #10 — Geo Scatter 地图空白
- **日期**：2026-06-13
- **现象**：Geo scatter 地图纯白，无散点
- **根因**：(1) data 格式错误 — `value: [lat, val, lng]` 应该是 `[lng, lat, val]`；(2) 没有 China GeoJSON
- **修复**：数据列顺序修正为 `[lng, lat, val]`；确认 china.js 已内联

### #11 — Geo Scatter 点大小都相同
- **日期**：2026-06-13
- **现象**：所有 geo scatter 点一样大，数据值差异不可见
- **根因**：(1) 用 `visualMap` 映射 symbolSize 但 dimension 索引在 geo 模式下不可靠；(2) JS 回调函数 `symbolSize(val)` 收到的 `val` 是 `{name, value: [lng,lat,val]}` 对象而非数组，`val[2]` 取到 undefined
- **修复**：在 Python 侧计算每点的 symbolSize，直接写入 `data[i].symbolSize` 属性（ECharts 原生支持）

### #12 — Geo Scatter tooltip 显示错误值
- **日期**：2026-06-13
- **现象**：鼠标悬停北京显示 39.9（纬度）而非 100（数据值）
- **根因**：`encode: {value: "val", lng: "lng", lat: "lat"}` 引用了不存在的 dataset 维度名。无 dataset 时 encode 必须用数值索引
- **修复**：改为 `encode: {lng: 0, lat: 1, value: 2}` — 数值索引对应 value 数组位置

### #13 — 图表无 tooltip
- **日期**：2026-06-13
- **现象**：鼠标悬停图表无数据显示
- **根因**：option 中没有显式 `tooltip: {}`（ECharts 默认开启但有时被覆盖）
- **修复**：在 `generate_echarts_html` 中强制注入 `tooltip: {}` + `toolbox: {saveAsImage, dataView}`

---

## 图表类型 → 数据格式速查

| 类型 | 数据格式 | 特殊要求 |
|------|----------|----------|
| bar / line / scatter(cartesian) | `dataset.source` + `encode` | — |
| scatter bubble | `dataset.source` + `encode: {x,y,z}` | 需要 `visualMap {inRange: {symbolSize}}` |
| scatter geo | `series.data: [{name, value: [lng,lat,val]}]` | `encode: {lng:0, lat:1, value:2}` |
| pie | `series.data: [{name, value}]` | `radius: ["40%","70%"]` |
| map | `series.data: [{name, value}]` | 需要 `visualMap {min,max,inRange:{color}}` |
| radar | `series.data: [{name, value: [d1,d2,...]}]` | value 是数组 |
| funnel | `series.data: [{name, value}]` | — |
| gauge | `series.data: [{value, name}]` | — |
| candlestick | `dataset.source` + `encode:{x, y:[lo,hi,o,cl]}` | — |
| heatmap | `dataset.source` + `xAxis/yAxis` | 需要 `visualMap {inRange:{color}}` |
| treemap / sunburst | `series.data` (嵌套 children) | — |
| sankey | `series.data + series.links` | — |
| graph | `series.data + series.links` | `layout: "force"` |
| tree | `series.data` (嵌套 children) | — |
| 3D (bar3D/scatter3D/surface/line3D) | `dataset.source` + `encode` | 需要 `echarts-gl.min.js` |
| globe | — | 需要 `echarts-gl.min.js` |
| geo lines | `series.data: [{coords: [[lng,lat],...]}]` | `coordinateSystem: "geo"` |
| timeline | `timeline.data + options[]` | — |
| parallel | `parallelAxis + encode` | — |
| themeRiver | `series.data` | — |
| pictorialBar | `series.data` | — |
| chord | `series.data + series.links` | — |
| boxplot | `dataset.source + encode` | — |
| calendar | `calendar + visualMap` | — |

---

## #14 — Line XY 数据未排序导致折线锯齿
- **日期**：2026-06-13
- **现象**：08_Line_XY 折线来回穿梭，线条混乱
- **根因**：XY 折线图数据 `[[x,y],...]` 中 x 值未排序。ECharts line chart 按数组顺序连接点，不按 x 值排序
- **修复**：(1) 数据按 x 排序；(2) **模板 `line/xy.html` 新增 `data.sort()` 自动排序**，确保无论输入数据是否有序都能正确渲染

---

## #15 — 模板 {{PLACEHOLDER}} 未提供导致 JS 语法错误
- **日期**：2026-06-13
- **现象**：38/41 图表 JS 中出现 `var data = {{INCREASE}}` 等未替换占位符
- **根因**：`build_template.py` 对数据 dict 中不存在的 key 保留原文 `{{KEY}}`
- **修复**：生成前读取每个模板的全部 `{{PLACEHOLDER}}`，验证数据 dict 所有 key 都存在后才调用 `build()`；生成后检查无残留占位符

---

## #16 — Stacked bar/line 模板 series 缺少 type 字段
- **日期**：2026-06-13
- **现象**：03_Bar_Stacked、07_Line_Stacked 无数据
- **根因**：`bar/stack.html` 和 `line/stack.html` 使用 `{{SERIES}}` 替换整个 series 数组，每个 series 对象必须带 `type: "bar"/"line"`。ECharts 没有默认 series type
- **修复**：数据 dict 中 series 对象添加 `"type": "bar"` 或 `"type": "line"`

---

## #17 — Pie 模板 roseType/RADIUS 类型错误导致空白
- **日期**：2026-06-13
- **现象**：09_Pie_Basic 空白，无任何图表
- **根因**：(1) `ROSE_TYPE: ""` → JS 中变成 `roseType: ''`（空字符串），ECharts 不接受空串，只接受 `false`/`'radius'`/`'area'`；(2) `RADIUS: "['40%','70%']"` 被 `_json_safe` 当作字符串处理，单引号 JSON 解析失败，输出为带转义的字符串而非数组
- **修复**：(1) `ROSE_TYPE: "false"` → `_json_safe` 识别为 JS keyword，输出 `false`；(2) `RADIUS` 改为 Python list `["40%","70%"]` → `_json_safe` 用 `json.dumps` 正确序列化为 JS 数组 `["40%","70%"]`；(3) **模板 `pie/basic.html` 增加防御**：`roseType` 默认为 `false` 当值为空串时

---

## #18 — Scatter Geo/Map 空白：MAP_INLINE 被替换导致地图未加载
- **日期**：2026-06-13
- **现象**：12_Scatter_Geo、13_Map_China 等地图类图表空白
- **根因**：数据 dict 中 `"MAP_INLINE": ""` → `_json_safe` 替换 `{{MAP_INLINE}}` 为 `''` → `<!-- {{MAP_INLINE}} -->` 变成 `<!-- '' -->` → `build_template.py` 的地图注入检测 `if "<!-- {{MAP_INLINE}} -->" in html` 失败 → China GeoJSON 未嵌入 → 地图空白
- **修复**：**不要在数据 dict 中提供 `MAP_INLINE`/`GL_INLINE`/`ECHARTS_INLINE` 这三个特殊占位符**。它们由 `build_template.py` 自动处理（代码中已排除此三类占位符的校验）。**模板不需要修改**——模板中的 `<!-- {{MAP_INLINE}} -->` 本身就是正确的，只需调用方不覆盖它

---

## #19 — Scatter Geo 气泡大小无差异
- **日期**：2026-06-13
- **现象**：12_Scatter_Geo 所有气泡一样大
- **根因**：模板 `symbolSize: function(val) { return Math.sqrt(val[2]) / SIZE_SCALE || 8; }` 中 `Math.sqrt` 压缩了数值差异。值 70-100 经 sqrt 后为 8.4-10，差值仅 1.6px，肉眼不可分辨
- **修复**：模板改为 `val[2] / {{SIZE_SCALE}}`（线性），SIZE_SCALE=5 → 14-20px 可分辨范围

---

## #20 — Treemap 父节点缺少 value 导致布局错误
- **日期**：2026-06-13
- **现象**：19_Treemap 布局比例失调，标签只显示根节点名称
- **根因**：(1) 父节点没有 `value` 属性，ECharts treemap 无法按比例分配面积；(2) 数据只有 2 大类 4 项，过于稀疏；(3) `UPPER_LABEL_SHOW: false` 导致上层标签不显示
- **修复**：(1) 父节点添加 `value`（子节点之和）；(2) 扩充为 3 大类 11 项；(3) `UPPER_LABEL_SHOW: true`；(4) **模板增加防御**：`upperLabel.show` 和 `breadcrumb.show` 在值为空时默认为 `true`

---

## #21 — Sunburst 空白：RADIUS 字符串 + FOCUS 值非法
- **日期**：2026-06-13
- **现象**：20_Sunburst 一片空白
- **根因**：(1) `RADIUS: "['0%','90%']"` — 字符串假数组，同 #17 pie 的问题，`_json_safe` 将其当作字符串处理；(2) `FOCUS: "none"` — ECharts sunburst `emphasis.focus` 只接受 `'ancestor'` 或 `'descendant'`，不接受 `'none'`
- **修复**：(1) `RADIUS` 改为 `D(["0%","90%"])` — JSON 数组；(2) `FOCUS: "ancestor"`；(3) **模板增加防御**：`radius: {{RADIUS}} || ["0%","90%"]` 和 `focus: {{FOCUS}} || "ancestor"`

---

## #22 — Tree 空白：DATA 是对象而非数组
- **日期**：2026-06-13
- **现象**：23_Tree 一片空白
- **根因**：ECharts tree 的 `data` 必须是数组 `[{root}]`，但传入的是单个对象 `{name:"CEO",...}`
- **修复**：(1) DATA 改为 `D([{...}])` — 包裹在数组中；(2) **模板增加防御**：`data: [].concat({{DATA}})` — `[].concat(obj)` 自动包数组，`[].concat(arr)` 保持不变

---

## #23 — Boxplot 空白：依赖缺失的 ecStat 库
- **日期**：2026-06-13
- **现象**：24_Boxplot 一片空白
- **根因**：原模板使用 ECharts `transform: { type: 'boxplot' }`，需要 `ecStat` 扩展库，但项目中不存在该库
- **修复**：(1) 模板重写为预计算五数概括格式 `series.data: [[min, Q1, median, Q3, max], ...]`，无需 ecStat；(2) 数据从原始值改为 `[[740,880,935,980,1070],[800,860,900,940,960]]`

---

## #24 — PictorialBar：symbol 必须用真实位图，SVG/矢量路径效果差
- **日期**：2026-06-13
- **现象**：28_PictorialBar 显示纯色方块，无象形效果
- **根因**：(1) `SYMBOL: "rect"` → 普通矩形，不"象形"；(2) SVG 手绘路径质量差；(3) `SYMBOL_BOUNDING: "false"` → 无 bounding，所有值显为单个图标
- **修复**：(1) 下载 Twitter emoji CDN 的 72x72 PNG 光栅图（大象/犀牛/河马/水牛/长颈鹿）；(2) 通过 `data[i].symbol` 为每个数据项设置独立图标 URI；`symbolBoundingData: 1000`，`symbolRepeat: true`；(3) **模板增加防御**：`symbol` 为空时允许 data[i].symbol 覆盖

---

## #25 — EffectScatter 空白 + 颜色不生效
- **日期**：2026-06-13
- **现象**：30_EffectScatter 一片空白，修复后各城市同色
- **根因**：(1) `GEO_COORD_MAP: "{}"` 空对象，`MAP_NAME: ""` 空地图名 → 无地图；(2) `convertData()` 只复制 `name`/`value`，丢弃 `itemStyle`
- **修复**：(1) 提供真实 GEO_COORD_MAP + MAP_NAME="china"；(2) `convertData` 保留 `itemStyle`；(3) 每城市设不同颜色 `itemStyle.color`；(4) **模板守卫**：`geoCoordMap || {}`，`map || "china"`

---

## #26 — Lines/Flights 空白 + 线宽过粗
- **日期**：2026-06-13
- **现象**：31_Lines_Flights 空白，修复后线宽 80-100px
- **根因**：(1) FLIGHTS 格式错误——传入对象 `{fromName,...}` 而非数组 `[from,to,val]`，模板 `item[0]` 取到 undefined；(2) GEO_COORD_MAP 为空 `{}`；(3) 线宽公式 `value/LINE_SCALE` 用 LINE_SCALE=1 导致 80-100px 宽
- **修复**：(1) FLIGHTS 改为 `[["北京","上海",100],...]`；(2) GEO_COORD_MAP 提供真实坐标；(3) `lineStyle.width` 固定为 `1`，删掉动态计算

---

## #27 — 3D Bar 空白：GL_INLINE + coordinateSystem + zAxis3D 配置错误
- **日期**：2026-06-13
- **现象**：33_3D_Bar 一片空白
- **根因**：(1) `GL_INLINE: ""` 破坏 echarts-gl 注入（同 #18）；(2) `coordinateSystem: 'cartesian3D'` + `zAxis3D: {type:'value'}` + `shading:'realistic'` 不是官方推荐的配置组合；(3) 官方示例用 `zAxis3D: {}`（空对象）、无 `coordinateSystem`、`shading: 'lambert'`
- **修复**：模板改为与 ECharts 官方 bar3D 示例完全一致的配置：`grid3D: {}`、`zAxis3D: {}`、`shading: 'lambert'`、无 `coordinateSystem`、无 `barSize`

---

## #28 — 3D Scatter/Surface/Globe/Lines3D 同样空白
- **日期**：2026-06-13
- **现象**：34/35/36/37 全部空白
- **根因**：与 #27 相同——GL_INLINE 破坏注入 + 模板配置偏离官方示例。所有 3D 模板统一修复
- **修复**：3d/scatter3d.html、3d/surface.html、3d/globe.html、3d/lines3d.html 全部改为与官方示例一致的配置。关键：`zAxis3D: {}`（非 `{type:'value'}`）、`grid3D: {}`、无 `coordinateSystem`

---

## #29 — Surface 空白：JS 函数被 `_json_safe` 加引号变成字符串
- **日期**：2026-06-13
- **现象**：35_3D_Surface 空白，JS 函数 `function(x,y){...}` 被当成字符串输出 `'function(x,y){...}'`
- **根因**：`build_template.py` 的 `_json_safe` 不支持函数字符串，所有字符串值都被包在引号中
- **修复**：(1) `_json_safe` 新增检测：以 `function` 或 `(` 开头的字符串直接原样返回；(2) surface 模板改为与官方示例一致的 `equation: {x,y,z}` 结构

---

## #30 — Globe 无纹理显示为纯色/空白球
- **日期**：2026-06-13
- **现象**：36_3D_Globe 显示为纯蓝/黄色球，无地球纹理
- **根因**：未提供 `baseTexture`，ECharts globe 渲染为无纹理球体
- **修复**：下载 ECharts 官方示例的 1.3MB JPG 地球纹理（`echarts.apache.org/examples/data-gl/asset/world.topo.bathy.200401.jpg`），base64 嵌入为 `baseTexture`

---

## #31 — Lines3D 空白：GEO_COORD_MAP 为空 + BASE_TEXTURE 缺失
- **日期**：2026-06-13
- **现象**：37_3D_Lines3D 一片空白
- **根因**：(1) `GEO_COORD_MAP: "{}"` 空对象，FLIGHTS 使用不存在的地名 "A/B/C"；(2) `BASE_TEXTURE: ""` 无地球纹理；(3) GL_INLINE 破坏注入（同 #18）
- **修复**：(1) GEO_COORD_MAP 提供真实城市经纬度；(2) FLIGHTS 改用真实城市名 `[["北京","上海"],...]`；(3) BASE_TEXTURE 使用真实地球纹理；(4) **模板守卫**：`geoCoordMap || {}`

---

## #32 — Error Bar 空白：custom renderItem 函数无法通过占位符传递
- **日期**：2026-06-13
- **现象**：39_Custom_Error_Bar 空白
- **根因**：(1) `RENDER_ITEM: "false"` → 无渲染函数，custom 类型不知道该画什么；(2) 多行 JS 函数无法通过 Python 字符串占位符传递（换行导致语法错误）
- **修复**：(1) `renderItem` 直接硬编码在模板中；(2) 模板简化为只需 `DATA` 占位符；(3) 误差线红色 `#e54035`，柱体蓝色 `#5470c6`

---

## #34 — Timeline OPTIONS 为空 + yAxis 不固定
- **日期**：2026-06-13
- **现象**：41_Mix_Timeline 数据不随时间变化，且 y 轴跳动
- **根因**：(1) `OPTIONS: "[]"` → 空数组，baseOption 的系列数据不变；(2) VGG 中没有 `yAxis.max`，不同时期数据范围不同导致 y 轴自动缩放
- **修复**：(1) OPTIONS 提供每个时间点的 `series.data`；(2) baseOption `yAxis.max: 200` 固定；(3) **模板改进**：`OPTIONS` 占位符改为非空默认 `[]`

---

## #33 — Geo Lines 与官方示例完全不符
- **日期**：2026-06-13
- **现象**：40_Geo_Lines 从空白→线条不可见→纯色线→最终修复
- **根因**：(1) 多次偏离官方示例，自己创造配置；(2) 官方「模拟迁徙」示例有 3 层 series（粒子飞线+箭头线+涟漪散点）和 planePath 飞机图标
- **修复**：模板完全按官方 `geo-lines` Migration 示例重写——`backgroundColor: '#404a59'`、3 层 series、planePath SVG、`convertData` 城市名→坐标转换、18 条路线
| effectScatter | `series.data` | — |
