
# 描述钢结构模型的Json对象需要遵循以下结构

-  Schema_Version: `v6.1.2`

## 强制规范
- 字段名必须与 schema 完全一致; 工具调用必须使用 schema 原始英文键; 面向用户的自然语言输出不得展示英文键名.
- 截面表中所有截面编号必须从 1 开始且连续递增(包括 LT/CG/XLT/LTC/GZ/GL/ZC/XG/WM/QM/YP/YLT/MZ/ML/CZ/CL 等)
- 截面表只包含被引用的截面编号;若业务规则明确要求保底编号,则允许保留该最小保底集合
- 新建模型(POST `/api/assemblies`)时, `originData` 必须完整输出全部一级子系统及 required 字段.
- 修改模型(PATCH)时, `patch_data` 仅包含本次变更键, 不要求提交未变更 required 字段.
- 禁止输出 N/A
- 数值不带单位(m,mm,kN/m2 等仅用于理解)
- 除截面规格字符串外,所有长度/标高/坐标统一使用 m 作为数值基准

## 字段格式规范

| 字段 | 类型 | 格式要求 |
|------|------|----------|
| version | string | 必须使用`Schema_Version`的值 |
| factory_length | number | 正数,单位 m,等于列距总和 |
| factory_width | number | 正数,单位 m,等于跨宽总和 |
| span_count | integer | 正整数,必须等于 span_widths 数组长度 |
| span_widths | array | 非空数组,每个元素为正数(单位 m) |
| floor_count | integer | 正整数,默认 1 |
| roof_type | string | 枚举值:双坡单屋脊/单坡/平屋面/多屋脊 |
| structure_type | string | 枚举值:门式刚架/桁架/网架 |
| eave_height | number | 正数,单位 m |
| slope_denominator | integer | 正整数,默认 20 |
| x_main_axis_coors | object | 键为 "1".."n" 连续编号,值为坐标(从 0 起累加) |
| y_main_axis_coors | object | 键为 "A".."Z"/"AA".. 连续编号,值为坐标(从 0 起累加) |
| y_ridge_axis | object | {"WJ*": <y坐标>} 或 {}(不满足条件时) |
| z_main_axis_coors | object | 必含 FND, FL1, EAVE=eave_height;可选 CB1..CBn, FL2..FLn |
| dead.* | number/string | 除枚举字段外均为数值或 `""`;pv/suspended/concentrated 缺失可为 0.0 |
| live.roof_accessible_category | string | 枚举:不上人的屋面/上人的屋面 |
| live.roof_live_need_combine_with_wind_snow | boolean/string | boolean 或 `""` |
| wind.w0_R50_kN_per_m2 | number/string | 数值或 `""`,且数值下限 0.3 |
| snow.snow_zone | string | 枚举:I/II/III |
| crane.has_crane | boolean/string | boolean 或 `""` |
| crane.crane_weight_t/crane_count | integer/string | 非负整数或 `""` |
| corner_column_sections | object | 键 `"X-Y-Z1:Z2"`(如 `"1-A-FL1:ROOF"`),值 GZ* 编号 |
| end_column_sections | object | 键 `"X-Y-Z1:Z2"`(如 `"1-B-FL1:ROOF"`),值 GZ* 编号 |
| side_column_sections | object | 键 `"X-Y-Z1:Z2"`(如 `"2-A-FL1:ROOF"`),值 GZ* 编号 |
| inner_column_sections | object | 键 `"X-Y-Z1:Z2"`(如 `"2-B-FL1:ROOF"`),值 GZ* 编号;无则 {} |
| wind_column_sections | object | 键 `"X-Yw-Z1:Z2"`(如 `"1-A1w-FL1:ROOF"`),Yw 来自 y_wind_column_aux_axes 的键,值 GZ* 编号;无则 {} |
| column_section_table | object | 键 GZ1..GZn 连续编号,值含 section/material/note |
| main_beam_sections | object | 键 `"X-Y1:Y2-ROOF"`,值为分段序列 "GL1-GL2-...|GL..." |
| main_beam_tapered_y_pos | object | 键与 main_beam_sections 一致,值为坐标数组(节点数=段数+1) |
| end_beam_sections | object | 键 `"X-Y1:Y2-ROOF"`,值 GL* 编号, 若分段则与main_beam_sections一致 |
| end_beam_tapered_y_pos | object | 键与 end_beam_sections 一致,值为坐标数组 |
| beam_section_table | object | 键 GL1..GLn 连续编号,值含 section/material/note |
| y_wind_column_aux_axes | object | 键格式 "<跨名><序号>w"(如 A1w),值为 Y 坐标;无则 {} |
| y_mid_span_column_axes | object | 键格式 "<跨名><序号>m"(如 A1m),值为 Y 坐标;无则 {} |
| z_aux_axis_coors | object | 新增标高(如 CB1),无则 {} |
| crane_operation_range | object | 键 `"X1:X2-Y1:Y2-CB*"`(吊车运行范围+标高),值为吊车吨位;无吊车则 {} |
| crane_beam_sections | object | 键 `"X1:X2-Y-CB*"`(吊车梁位置+标高),值为吊车梁型号;无吊车则 {} |
| roof_panel_section | string | 屋面板编号 WM* |
| roof_panel_boundary_sequences | array | 二维数组,每块 4 个角点 `"X-Y-Z"`(如 `"1-A-ROOF"`) |
| wall_panel_section | string | 墙面板编号 QM* |
| wall_panel_boundary_sequences | array | 二维数组,每块 4 个角点 `"X-Y-Z"` |
| short_wall_type | string | 枚举值:钢混矮墙/砌体矮墙 |
| short_wall_ranges | array | 矮墙定位 `"X1:X2-Y-0:<高>@<厚>"` 或 `"X-Y1:Y2-0:<高>@<厚>"`;无矮墙则 [] |
| panel_section_table | object | 键 WM*/QM* 编号,值含 section/material/note |
| x_opening_aux_axes | object | 门窗 X 向辅助轴线,键 XW*,值为坐标(m);无则 {} |
| y_opening_aux_axes | object | 门窗 Y 向辅助轴线,键 YW*,值为坐标(m);无则 {} |
| z_opening_aux_axes | object | 门窗 Z 向辅助轴线,键 ZW*,值为标高(m);无则 {} |
| x_side_door | object | 侧墙门,键"X左:X右-Y-Z下:Z上",值"<MZ*>-<ML*>";无则 {} |
| y_end_door | object | 山墙门,键"X-Y左:Y右-Z下:Z上",值"<MZ*>-<ML*>";无则 {} |
| x_side_window | object | 侧墙窗,键"X左:X右-Y-Z下:Z上",值"<CZ*>-<CL*>-<CL*>";无则 {} |
| y_end_window | object | 山墙窗,键"X-Y左:Y右-Z下:Z上",值"<CZ*>-<CL*>-<CL*>";无则 {} |
| door_window_section_table | object | 键 MZ*/ML*/CZ*/CL* 编号从 1 起连续,值含 section/material/note |
| skylight_positions | object | 键 ZQC1..ZQCn,值为 [x1,y1,x2,y2] 矩形坐标;无天窗则 {} |
| skylight_material | object | 键与 skylight_positions 一致,值为材料类型;无天窗则 {} |
| canopy_positions | object | 键 `"X1:X2-Y-<根部标高>@<深度>"`(如 `"2:4-A-4.5@2.5"`),值 `"YP*-YLT*-XG*"`;无雨篷则 {} |
| canopy_slope_direction | string | 枚举值:向下倾斜/向上倾斜 |
| canopy_support_form | string | 格式 "上拉式@30°" 或 "下撑式@45°"(角度 30°~60°) |
| canopy_slope_denominator | integer | 雨篷坡度分母,默认 40(30~50) |
| canopy_section_table | object | 键 YP*/YLT*/XG* 编号从 1 起连续,值含 section/material/note;无雨篷则 {} |
| y_tie_rod_aux_axes | object | 键格式 "T<序号>r"(如 T1r),值为 Y 坐标;无则 {} |
| roof_tie_rod_sections | object | 键 `"X1:X2-Y-ROOF"`,值 XG* 编号;无则 {} |
| column_tie_rod_sections | object | 键 `"X1:X2-Y-CB1"`或 `"X-Y1:Y2-CB1"`(使用标高名),值 XG* 编号 |
| column_bracing_form | string | 枚举值:X形/V形/K形 |
| column_bracing_sections | object | 键 `"X1:X2-Y-Z1:Z2"`(如 `"2:3-A-FL1:ROOF"`),值 ZC* 编号 |
| roof_horizontal_bracing_form | string | 枚举值:X形/V形 |
| roof_horizontal_bracing_sections | object | 键 `"X1:X2-Y1:Y2-ROOF"`(相邻系杆线),值 ZC* 编号 |
| bracing_section_table | object | 键 XG*/ZC* 连续编号,值含 section/material/note |
| roof_purlin_spacing | number | 檩条间距,默认 1.5(单位 m) |
| roof_purlin_section | string | 檩条截面编号 |
| side_wall_purlin_spacing | number | 侧墙檩条间距,默认 1.5(单位 m) |
| side_wall_purlin_section | string | 侧墙檩条截面编号 |
| end_wall_purlin_spacing | number | 山墙檩条间距,默认 1.5(单位 m) |
| end_wall_purlin_section | string | 山墙檩条截面编号 |
| roof_tie_bar_sections | array | 屋面拉条截面数组 [撑杆, 斜拉条, 直拉条] |
| side_wall_tie_bar_sections | array | 侧墙拉条截面数组 |
| end_wall_tie_bar_sections | array | 山墙拉条截面数组 |
| purlin_section_table | object | 键 LT*/QLT*/CG*/XLT*/LTC* 编号,值含 section/material/note |

## 构件定位格式规范

所有构件使用轴线以及辅助轴线定位装配位置

### 核心格式

```
<X轴>-<Y轴>-<Z轴>
```

- **`-`** 分隔不同类型轴线(X,Y,Z)
- **`:`** 表示同一类型轴线的区间范围

### 定位格式类型

| 类型 | 格式 | 示例 | 说明 |
|------|------|------|------|
| 单点定位 | `X-Y-Z` | `2-A-CB1` | 单个位置的构件(如系杆节点) |
| 点+高度范围 | `X-Y-Z1:Z2` | `2-A-FL1:ROOF` | 竖向构件(如柱) |
| X区间定位 | `X1:X2-Y-Z1:Z2` | `2:3-A-FL1:CB1` | 沿X向布置(如柱间支撑) |
| Y区间定位 | `X-Y1:Y2-Z` | `2-A:B-ROOF` | 沿Y向布置(如主梁) |
| XY区间定位 | `X1:X2-Y1:Y2-Z` | `2:9-A:B-CB1` | 平面区域(如吊车运行范围) |

### 关键字约定(强制)

1. 使用固定关键字 `ROOF` 表示屋面标高
2. 除第一条定义的固定关键字外, 定位格式中使用的 X*, Y*, Z* 关键字必须使用已经定义在主轴线或辅助轴线中的键名

## Json定义
<JsonSchema>
```json
{
  "version": <Schema_Version>,

  "basic_params": {
    "factory_length": <number>,
    "factory_width": <number>,
    "span_count": <integer>,
    "span_widths": [<number>, ...],
    "floor_count": <integer>,
    "roof_type": "<双坡单屋脊|单坡|平屋面|多屋脊>",
    "structure_type": "<门式刚架|桁架|网架>",
    "eave_height": <number>,
    "slope_denominator": <integer>
  },
  "grid_system": {
    "x_main_axis_coors": {"1": 0, "2": <number>, "3": <number>, ...},
    "y_main_axis_coors": {"A": 0, "B": <number>, "C": <number>, ...},
    "z_main_axis_coors": {
      "FND": <number>,
      "FL<n>": <number>,
      "CB<n>": <number>,
      "EAVE": <number>
    }
  },
  "ridge_aux_axis": {
    "y_ridge_axis": {"WJ*": <number>} | {}
  },
  "load_params": {
    "dead": {
      "roof_dead_load_kN_per_m2": <number|"">,
      "roof_pv_load_kN_per_m2": <number|"">,
      "roof_suspended_load_kN_per_m2": <number|"">,
      "roof_concentrated_load_kN": <number|"">,
      "floor_dead_load_kN_per_m2": <number|"">,
      "equipment_load": <number|"">
    },
    "live": {
      "roof_accessible_category": "<不上人的屋面|上人的屋面>",
      "roof_live_load_kN_per_m2": <number|"">,
      "roof_live_psi_c": <number|"">,
      "roof_live_psi_r": <number|"">,
      "roof_live_psi_q": <number|"">,
      "roof_live_need_combine_with_wind_snow": <boolean|"">,
      "floor_live_load_kN_per_m2": <number|"">
    },
    "snow": {
      "s0_R50_kN_per_m2": <number|"">,
      "snow_zone": "<I|II|III|>",
      "psi_c": <number|"">,
      "psi_f": <number|"">,
      "psi_q": <number|"">
    },
    "wind": {
      "w0_R50_kN_per_m2": <number|"">,
      "psi_c": <number|"">,
      "psi_f": <number|"">,
      "psi_q": <number|"">
    },
    "crane": {
      "has_crane": <boolean|"">,
      "crane_weight_t": <integer|"">,
      "crane_count": <integer|"">,
      "crane_range": "<string>",
      "work_level": "<string>",
      "rail_top_elevation_m": <number|"">
    }
  },
  "frame_aux_axis": {
    "y_wind_column_aux_axes": {"<跨名><序号>w": <number>, ...} | {},
    "y_mid_span_column_axes": {"<跨名><序号>m": <number>, ...} | {},
    "z_aux_axis_coors": {"CB<n>": <number>, ...} | {}
  },
  "column_system": {
    "corner_column_sections": {"<X>-<Y>-<Z1>:<Z2>": "<GZ*>", ...},
    "end_column_sections": {"<X>-<Y>-<Z1>:<Z2>": "<GZ*>", ...},
    "side_column_sections": {"<X>-<Y>-<Z1>:<Z2>": "<GZ*>", ...},
    "inner_column_sections": {"<X>-<Y>-<Z1>:<Z2>": "<GZ*>", ...} | {},
    "wind_column_sections": {"<X>-<Yw>-<Z1>:<Z2>": "<GZ*>", ...} | {},
    "column_section_table": {
      "GZ1": {"section": "<截面规格>", "material": "Q355B", "note": "<用途说明>"},
      ...
    }
  },
  "beam_system": {
    "main_beam_sections": {"<X>-<Y1>:<Y2>-ROOF": "<GL*>-<GL*>-..|<GL*>.", ...},
    "main_beam_tapered_y_pos": {"<X>-<Y1>:<Y2>-ROOF": [<number>, ...], ...},
    "end_beam_sections": {"<X>-<Y1>:<Y2>-ROOF": "<GL*>-<GL*>-..|<GL*>.", ...},
    "end_beam_tapered_y_pos": {"<X>-<Y1>:<Y2>-ROOF": [<number>, ...], ...},
    "beam_section_table": {
      "GL1": {"section": "<截面规格>", "material": "Q355B", "note": "<用途说明>"},
      ...
    }
  },
  "crane_system": {
    "crane_operation_range": {"<X1>:<X2>-<Y1>:<Y2>-<CB*>": "<吊车吨位>", ...} | {},
    "crane_beam_sections": {"<X1>:<X2>-<Y>-<CB*>": "<截面型号>", ...} | {}
  },
  "bracing_aux_axis": {
    "y_tie_rod_aux_axes": {"T<序号>r": <number>, ...} | {}
  },
  "bracing_system": {
    "roof_tie_rod_sections": {"<X1>:<X2>-<辅助轴线>-ROOF": "<XG*>", ...} | {},
    "column_tie_rod_sections": {"<X1>:<X2>-<Y>-<Z>": "<XG*>", ...},
    "column_bracing_form": "<X形|V形|K形>",
    "column_bracing_sections": {"<X1>:<X2>-<Y>-<Z1>:<Z2>": "<ZC*>", ...},
    "roof_horizontal_bracing_form": "<X形|V形>",
    "roof_horizontal_bracing_sections": {"<X1>:<X2>-<Y1>:<Y2>-ROOF": "<ZC*>", ...},
    "bracing_section_table": {
      "XG1": {"section": "<截面规格>", "material": "Q235B", "note": "<用途说明>"},
      "ZC1": {"section": "<截面规格>", "material": "Q235B", "note": "<用途说明>"},
      ...
    }
  },
  "purlin_system": {
    "roof_purlin_spacing": <number>,
    "roof_purlin_section": "<LT*>",
    "side_wall_purlin_spacing": <number>,
    "side_wall_purlin_section": "<QLT*>",
    "end_wall_purlin_spacing": <number>,
    "end_wall_purlin_section": "<QLT*>",
    "roof_tie_bar_sections": ["<CG*>", "<XLT*>", "<LTC*>"],
    "side_wall_tie_bar_sections": ["<CG*>", "<XLT*>", "<LTC*>"],
    "end_wall_tie_bar_sections": ["<CG*>", "<XLT*>", "<LTC*>"],
    "purlin_section_table": {
      "LT1": {"section": "<截面规格>", "material": "Q235B", "note": "<用途说明>"},
      "CG1": {"section": "<截面规格>", "material": "Q235B", "note": "<用途说明>"},
      ...
    }
  },
  "panel_system": {
    "roof_panel_section": "<WM*>",
    "roof_panel_boundary_sequences": [
      ["<X>-<Y>-<Z>", "<X>-<Y>-<Z>", "<X>-<Y>-<Z>", "<X>-<Y>-<Z>"],
      ...
    ],
    "wall_panel_section": "<QM*>",
    "wall_panel_boundary_sequences": [
      ["<X>-<Y>-<Z>", "<X>-<Y>-<Z>", "<X>-<Y>-<Z>", "<X>-<Y>-<Z>"],
      ...
    ],
    "short_wall_type": "<钢混矮墙|砌体矮墙>",
    "short_wall_ranges": ["<X1>:<X2>-<Y>-0:<高度>@<厚度>", ...] | [],
    "panel_section_table": {
      "WM1": {"section": "<板型规格>", "material": "<材料>", "note": "<用途说明>"},
      "QM1": {"section": "<板型规格>", "material": "<材料>", "note": "<用途说明>"},
      ...
    }
  },
  "opening_aux_axis": {
    "x_opening_aux_axes": {"XW1": <number>, "XW2": <number>, ...} | {},
    "y_opening_aux_axes": {"YW1": <number>, "YW2": <number>, ...} | {},
    "z_opening_aux_axes": {"ZW1": <number>, "ZW2": <number>, ...} | {}
  },
  "opening_system": {
    "x_side_door": {"<X左>:<X右>-<Y>-<Z下>:<Z上>":"<MZ*>-<ML*>", ...} | {},
    "y_end_door": {"<X>-<Y左>:<Y右>-<Z下>:<Z上>":"<MZ*>-<ML*>", ...} | {},
    "x_side_window": {"<X左>:<X右>-<Y>-<Z下>:<Z上>":"<CZ*>-<CL*>-<CL*>", ...} | {},
    "y_end_window": {"<X>-<Y左>:<Y右>-<Z下>:<Z上>":"<CZ*>-<CL*>-<CL*>", ...} | {},
    "door_window_section_table": {
      "MZ1": {"section": "<截面规格>", "material": "Q235B", "note": "门柱"},
      "ML1": {"section": "<截面规格>", "material": "Q235B", "note": "门梁"},
      "CZ1": {"section": "<截面规格>", "material": "Q235B", "note": "窗柱"},
      "CL1": {"section": "<截面规格>", "material": "Q235B", "note": "窗梁"},
      ...
    }
  },
  "skylight_system": {
    "skylight_positions": {"ZQC<n>": [<x1>, <y1>, <x2>, <y2>], ...} | {},
    "skylight_material": {"ZQC<n>": "<PMMA|PC|FRP|安全玻璃>", ...} | {}
  },
  "canopy_system": {
    "canopy_positions": {"<X1>:<X2>-<Y>-<根部标高>@<深度>": "<YP*>-<YLT*>-<XG*>", ...} | {},
    "canopy_slope_direction": "<向下倾斜|向上倾斜>",
    "canopy_support_form": "<上拉式|下撑式>@<角度>°",
    "canopy_slope_denominator": <integer>,
    "canopy_section_table": {
      "YP1": {"section": "<截面规格>", "material": "Q235B", "note": "雨篷梁"},
      "YLT1": {"section": "<截面规格>", "material": "Q235B", "note": "拉杆"},
      ...
    } | {}
  }
}
```
</JsonSchema>
