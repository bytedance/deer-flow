<schema_rules>
# 建模规则
在调用建模工具 `POST /api/assemblies` 时, 按照以下规则组织 `origindata`参数.

## 1. 通用规则
- 字段名必须与既有 schema 完全一致,禁止翻译,重命名,增删层级.
- 截面编号必须从 1 连续递增,且截面表仅包含被引用编号(规则要求保底编号除外).
- 所有构件的截面取值都必须严格使用对应 `*_section_table` 的键,禁止直接在构件对象中写截面规格字符串或写成 `2×ZC1` 这类"倍数×编号"形式.
- 截面字符串必须参数完整,不得缺项.
- 除截面规格字符串外,长度/坐标/标高均按 m 数值表达.
- 缺失信息默认按规则补全,禁止 `N/A/null/空推断/待确认`;但涉及安全或规范校核的关键荷载口径必须先澄清后再建模.
- 图集归一化结果缺失或字段为空时,按原默认规则回退.

## 2. 截面格式规范
- 截面字符串必须参数完整,禁止缺项或省略(如 H(450-350),C200×70 均非法).
- 统一使用"×"作为乘号;圆管/圆钢用"Φ/φ";方/矩形管用"□".
- 参数单位:截面规格使用 mm(仅截面字符串内使用 mm,其他位置统一 m).
- 允许的截面类型与格式:
  - H型钢:Hh×B×tf×tw 或 H(h1-h2)×B×tf×tw
  - 十字H:X(Hh1×B1×tf1×tw1+Hh2×B2×tf2×tw2)
  - 方/矩形管:□B×H×t
  - 圆管:ΦD×t;圆钢:ΦD
  - 角钢:L b×a×t
  - 槽钢:U h×b×t 或 U h×b×tf×tw(二选一,参数不得缺项)
  - C/Z型薄壁:C/Z h×b×c×t
- 构件适配要求:
  - 柱/梁:优先H型钢或十字H,允许方管或圆管
  - 墙梁/檩条/拉条:C/Z 为主,必要时可用 H
  - 支撑/系杆:圆钢/圆管/角钢/方管/槽钢/Z 型钢
  - 门窗构件:C 型钢或方管为主,避免 H 型钢
  - 雨篷梁:H 型钢或方管;雨篷支撑/拉杆:圆钢或角钢

## 3. basic_params
- 基本参数仅输出 schema 字段,不输出 `column_spacing` 等中间量.
- `span_count`,span_widths,eave_height,`slope_denominator` 以用户输入优先.
- 缺省默认:`floor_count`=1,`roof_type`="双坡单屋脊",`structure_type`="门式刚架",`slope_denominator`=20.
- `roof_type` 取值映射:双坡/单屋脊→"双坡单屋脊";多屋脊/多脊→"多屋脊";其余为"单坡"/"平屋面".
- `factory_length`=列距总和,`factory_width`=跨宽总和;如用户已提供,需校验一致,不一致时以用户输入为准.
- 若用户提供坡度为小数(如 0.05)或百分比(如 5%),换算 `slope_denominator`=round(1/坡度);若提供 1:n,则 `slope_denominator`=n.

## 4. grid_system 子系统
- `x_main_axis_coors` 键为 "1..n" 连续编号;坐标从 0 起按 `column_spacing` 逐段累加.
  - `column_spacing` 数量=主轴线数量-1;不足则用最后一个值补齐,超出则截断.
  - 若仅给出 `factory_length` 与开间数:按等分取 `column_spacing`
- `y_main_axis_coors`:键为 "A..Z/AA.." 连续编号;坐标从 0 起按 `span_widths` 逐段累加.
- `span_count` 必须等于 `span_widths` 数量;若不一致,以 `span_widths` 为准修正 `span_count`
- `z_main_axis_coors` 至少包含 `FND`(基础顶标高,默认0),`FL1`(一层楼面标高,默认0),`EAVE`=`eave_height`.
- `floor_count`>1 时,FL2..FLn 按用户需求设置,如用户需求未明确提及,则按 `eave_height`/`floor_count` 等分,并保证 `FLn` < `EAVE`.
- 若用户明确给出牛腿/轨顶标高:写入 `CB1`..`CBn`.
- 若用户明确有吊车但未提供标高:默认写入 `CB1`=`eave_height`×0.75(保留 1 位小数).

## 5. ridge_aux_axis 子系统
- `y_ridge_axis`:仅当屋面类型为`双坡单屋脊`或`多屋脊`且屋脊位置不与任何一条主轴线重合时,设置屋脊辅助轴线 {"WJ*": y...},其余情况为 {}.

## 6. load_params 子系统
- 若用户提供但口径不清(kN 还是 kN/m²,设备载荷是集中还是均布等)则应当与客户确认后再执行建模;未提供则 `0.0`.
- `roof_accessible_category`:
  - 若用户明确不可上人/不上人 → `"不上人的屋面"`
  - 若用户明确可上人/上人 → `"上人的屋面"`
- `roof_live_load_kN_per_m2`:
  - 若用户给出数值:按 `roof_accessible_category` 执行下限校核(不上人≥0.5;上人≥2.0)
  - 若未提供:不上人取 `0.5`;上人取 `2.0`
- `roof_live_psi_c/roof_live_psi_r/roof_live_psi_q`:
  - 不上人的屋面:`0.7/0.5/0.0`
  - 上人的屋面:`0.7/0.5/0.4`
- `roof_live_need_combine_with_wind_snow`:
  - 不上人的屋面 → `false`
  - 上人的屋面 → `true`
- `floor_live_load_kN_per_m2`:按用户输入;缺失则 `0.0`.
- `snow.s0_R50_kN_per_m2/snow.snow_zone/snow.psi_c/snow.psi_f/snow.psi_q`:必须来自 `context_load_wind_snow.snow.*`.
- `wind.w0_R50_kN_per_m2/wind.psi_c/wind.psi_f/wind.psi_q`:必须来自 `context_load_wind_snow.wind.*`.

## 7. frame_aux_axis 子系统
- `y_wind_column_aux_axes`:当任一跨度>15m 时,**每个**大跨内至少 2 根抗风柱;间距建议 6~10m,尽量均匀且左右对称;Y 坐标不得与主轴线重合.
  - 命名:跨名=起始主轴线字母(如 AB 跨为 A),序号从 1 递增,格式:A1w,A2w...
- `y_mid_span_column_axes`:当单跨跨度>30m 时设置跨中柱轴线(命名 A1m,A2m...),Y 坐标不得与主轴线重合.

## 8. column_system 子系统
- 角柱:位于 X 首/末轴 与 Y 首/末轴交点.
- 端柱:位于 X 首/末轴 与中间 Y 轴交点.
- 边柱:位于 Y 首/末轴 与中间 X 轴交点.
- 内柱:位于中间 X/Y 主轴线交点,**不得使用抗风柱辅助轴线交点**.
- 抗风柱:位于 **X 首轴/末轴(两端山墙)** 与 **`y_wind_column_aux_axes`** 的交点,写入 `wind_column_sections`;不得与四类主柱字段重复输出同一定位键.
- `columns.side_column_section` 优先用于 corner/end/side.
- `columns.inner_column_section` 统一用于 inner（包含中柱与摇摆柱语义）.
- 抗风柱截面:若图集归一化结果可解析且包含抗风柱相关语义字段,优先采用;并在 note 标注"抗风柱".
- **有吊车时柱分段**:分别定义下柱和上柱:
  - 下柱:`"2-A-FL1:CB1": "GZ1"`
  - 上柱:`"2-A-CB1:ROOF": "GZ2"`
- `column_section_table`:编号从 GZ1 递增,格式 {"section": "...", "material": "Q355B", "note": "..."}.
  - 若 wind_column_sections 非空,必须在 `column_section_table` 中为抗风柱分配**独立**的 GZ* 编号(即使截面规格与其他柱相同也禁止复用编号),note 写明"抗风柱".

## 9. beam_system 子系统
- **梁定位格式**:`X-Y1:Y2-Z`,Z 使用标高名 `ROOF`(沿屋面布置).
- `main_beam_sections`:键格式 `"X-Y1:Y2-ROOF"`,值为分段序列(使用 "|" 表示镜像).左右镜像分段必须显式列出(如 `"GL1-GL2-GL3|GL4-GL5-GL6"`).
- `main_beam_sections` 必须包含 "|" 镜像,禁止输出无 "|" 的完全展开序列.
- 主梁必须从最小Y主轴线覆盖到最大Y主轴线,同一X轴线只输出一条主梁键;禁止按单跨拆分 `main_beam_sections`(如两跨时输出 `"2-A:C-ROOF"`,不要输出 `"2-A:B-ROOF"` 与 `"2-B:C-ROOF"`).
- `end_beam_sections`:默认与相邻主梁一致.
- `beam_section_table`:编号从 GL1 递增,格式 {"section": "...", "material": "Q355B", "note": "..."}.
- IMPORTANT:
  - `main_beam_tapered_y_pos` 的节点数必须等于分段数+1,因为其每两个相邻的节点位置代表梁段的左右端点位置
### 主梁/端梁截面与分段
- 从图集归一化结果读取梁段截面: `beams.beam_segments`.
- 图集归一化梁段表示每榀门架(全跨)半个门架的分段,单坡表示半坡,双坡单屋脊表示左坡,双坡多屋脊表示每个双坡左坡.
- 图集归一化结果已给出段数/长度/截面时必须采用;完全不匹配视为异常并回退.
- 门式刚架屋面梁优先采用变截面梁;若图集归一化结果为等截面或单段梁,允许等截面,禁止强行分段.
- 段数拼接规则(必须使用 "|" 镜像表达,禁止展开为单序列):
  - 5 段→10 段:1-2-3-4-5|6-7-8-9-10
  - 3 段→6 段:1-2-3|4-5-6
  - 2 段→4 段:1-2|3-4
  - 1 段→2 段:1|2
- H(h1-h1) 视为无效,当 h1=h2 时必须输出 Hh1×...(等截面写法),禁止 H(h1-h1)×....
- 相邻梁段连接点的截面高度必须连续一致:例如相邻两个分段GL1和GL2,GL1的h2应当等于GL2的h1..
- `beam_section_table` 中镜像段必须交换 H1/H2(如 H(400-700) 镜像为 H(700-400)).
- 弯矩正值/负值大的位置应当使用高度较高的截面,弯矩接近0的位置可以使用高度较低的截面
- 施工可落图:梁高变化平缓,梁柱翼缘宽度接近,节点构造可施工.
### 主梁/端梁分段位置 `main_beam_tapered_y_pos`
- 优先使用 `beams.beam_lengths_m`,否则回退规则:
  - 前置条件:`beams.beam_lengths_m` 存在且 `span_count`∈{1,2,3}.
  - 单跨:L1+L2(+L3)=跨度/2;rest 按等式反推.
  - 双跨:L1+L2+L3=跨度;rest 按等式反推.
  - 三跨:L1+L2=跨度 且 L3+L4+L5=跨度/2;rest 按等式反推.
  - 若图集归一化结果跨度/跨数与输入不一致,允许调整:
    - 单跨:调整 L1
    - 双跨:调整 L2
    - 三跨:调整 L2 与 L4
    - 调整后任一长度为负或仍不满足等式→回退
  - 若等式不成立或出现负值,回退到下列默认:
    - 单跨:L≤24→1段;24<L≤30→2段(L2=3);30<L≤36→3段(L2=10,L3=3)
    - 双跨:固定 3 段,L2/L3 取 07SG518-4 标准值,L1=跨度-L2-L3
    - 三跨:固定 5 段,L2/L3/L5 取标准值,L1=跨度-L2,L4=跨度/2-L3-L5
  - `span_count`≥4:每跨至少 2 段;边跨至少 3 段;中跨段数应多于边跨.且需依据弯矩分布确定分段位置.
  - 分段节点必须包含柱顶,跨中与零弯矩点;无法精确计算时零弯矩点取 0.2L~0.25L.
  - 多跨时变截面梁高大端必须布置在柱顶(主轴线交点).
  - `main_beam_tapered_y_pos` 的分段位置数量必须与分段数量匹配(节点数=分段数+1,分段数=`main_beam_sections` 左序列长度+右序列长度).
  - 分段位置应当与主梁弯矩最大/最小/正负弯矩变化的位置匹配,负弯矩峰值在柱顶,正弯矩峰值在跨中.
  - 不等跨:对每跨按其跨度 L 分别计算,再按跨序累加生成全跨 Y 节点.
  - 生成 Y 节点:从 0 起累计左半段,再镜像累计到总长;节点数=段数+1.

## 10. crane_system 子系统
- 判定依据:若用户需求明确说明包含吊车,则视为有吊车;否则视为无吊车.
- 无吊车时:`crane_operation_range` 与 `crane_beam_sections` 输出空对象.
- 有吊车时:
  - **吊车运行范围定位格式**:`X1:X2-Y1:Y2-CB1`,使用标高名 CB*.
  - **吊车梁定位格式**:`X1:X2-Y-CB1`,Y 为单个主轴线.
  - `crane_operation_range` 默认取 X 轴中间区间(2:(n-1))× 全部 Y 主轴线范围;若用户明确范围则优先.
  - 标高优先使用 `z_main_axis_coors` 中的 `CB*`;若不存在,取 `eave_height`×0.75(保留1位小数),并写入 `frame_aux_axis.z_aux_axis_coors`(如 {"CB1": 6})
  - `crane_beam_sections` 优先来自图集归一化结果;无结果时用最小合法默认值.

## 11. bracing_aux_axis 子系统
- `y_tie_rod_aux_axes`:全局唯一命名 T1r,T2r...;坐标全局唯一且不与主轴线重合
- 先构造内部有序基础轴线集合变量:`sorted_y_base_lines = sort(y_main_axis_coors + y_wind_column_aux_axes + WJ(若有))`.
- 若`sorted_y_base_lines`或更新后的`sorted_y_lines`任一相邻区间`(line[i], line[i+1])`跨度大于 9m,则必须在该区间内补充一条或多条系杆辅助轴线 `y_tie_rod_aux_axes`,且Y值必须为0.5的倍数.
- 补充完成后,必须更新`sorted_y_lines = sort(y_main_axis_coors + y_wind_column_aux_axes + WJ(若有) + y_tie_rod_aux_axes)`,并保证任一相邻Y区间均`<=9m`.

## 12. bracing_system 子系统
### 支撑截面来源
- 若图集归一化结果包含支撑/系杆截面则直接采用。
- 若 `seismic_intensity`=8,优先采用标题包含"抗震设防烈度<=8度"的支撑系统条目.
### 屋面系杆和支撑
- `roof_tie_rod_sections`:默认在主Y轴线、抗风柱辅助轴线、屋脊辅助轴线(WJ,若有)以及系杆辅助轴线(若有)处通长覆盖其对应的所有开间生成屋面系杆.若用户需求明确指定了位置,则需要首先在对应位置生成`y_tie_rod_aux_axes`,然后在更新`sorted_y_lines`后,按更新后的全部相邻开间生成屋面系杆.
- 屋面系杆需先于支撑生成,屋面支撑的端点必须落在系杆线上.
- **系杆定位格式**: `X1:X2-Y-ROOF`
#### 屋面支撑的X向区间
- 除非用户需求明确制定支撑位置,默认在第二以及倒数第二开间生成屋面水平支撑`roof_horizontal_bracing_sections`.
- 若厂房长度较大,需主动按 30~45m 间距在中间开间生成屋面支撑.
#### 屋面支撑的Y向区间
- `roof_horizontal_bracing_form` 仅允许:X形/V形.
- 仅允许使用更新后的`sorted_y_lines`中的相邻轴线配对:`(sorted_y_lines[i], sorted_y_lines[i+1])`.
- `roof_horizontal_bracing_sections` 的每个 `<Y1>:<Y2>` 必须来自上述相邻配对,禁止跳越中间轴线(如存在 B 时禁止 A:C).
- 在每个 X 区间内,需在所有相邻配对中进行布置,端点必须落在已生成的屋面系杆线上,截面统一取 ZC1(或图集归一化值).
### 柱间支撑
- **柱间支撑定位格式**:`X1:X2-Y-Z1:Z2`.
- `column_bracing_sections` 键格式:`"X1:X2-Y-Z1:Z2"`,Y 轴线只能来自 y_main_axis_coors 主轴线键.
- `column_bracing_form` 仅允许:X形/V形/K形;若输入出现"人字形",映射为 V形.
- **纵向区间X必须与 `roof_horizontal_bracing_sections` 使用的 X 区间完全一致**.
- 柱间支撑所在的Y位置默认覆盖完整的Y主轴线;
- 当 `factory_width`>60m 时,除边墙轴线外,必须至少包含一条内柱主轴线的柱间支撑.
- 当 `eave_height`>10m 时,柱间支撑必须分为下柱支撑和上柱支撑两条记录,不得使用单条 `"X1:X2-Y-FL1:ROOF"` 覆盖整个柱高.
- 柱间支撑分段标高优先复用已有 `CB*`;若无可直接复用的分段标高,则由模型结合檐高、吊车、柱间系杆与支撑布置自行判断合理分段位置,并先写入 `frame_aux_axis.z_aux_axis_coors`,再输出上下两段柱间支撑.
- 柱间支撑分段示例:
  - 无现成分段标高时:`"2:3-A-FL1:ZB1": "ZC1"`,`"2:3-A-ZB1:ROOF": "ZC2"`
  - 有吊车且采用 `CB1` 时:`"2:3-A-FL1:CB1": "ZC1"`,`"2:3-A-CB1:ROOF": "ZC2"`
- 下柱支撑必须为型钢截面;双片柱间支撑不得写成 `"2×ZC1"` 或 `"2×ZC10"` 这类形式,必须先在 `bracing_section_table` 中定义独立的 `ZC*` 编号,其 `section` 明确写为 `2×*` 形式(如 `2×L90×6`),再由 `column_bracing_sections` 引用该 `ZC*` 键.
### 柱间系杆与分段
- **柱间系杆定位格式**:`X1:X2-Y-Z`.
- `column_tie_rod_sections` 键格式:`"X1:X2-Y-CB1"`.
- `column_tie_rod_sections` 的纵向区间,**必须**和屋面水平支撑`roof_horizontal_bracing_sections` 的 X 区间相同(在相同的开间).
### 默认截面与截面表
- `bracing_section_table` 至少包含 XG1,ZC1(若未从图集归一化结果获得):
  - XG1:φ120×5
  - ZC1:φ16(支撑)
  - CG1:φ32×2.5(撑杆)
  - XLT1:φ12(斜拉条)
  - LTC1:φ12(直拉条)
- 材料默认 Q235B,note 简述用途.

## 13. purlin_system 子系统
- 屋面檩条`roof_purlin_section`、侧墙梁`side_wall_purlin_section`与端墙梁`end_wall_purlin_section`优先使用图集归一化结果:
  - `purlin.roof_purlin_section_spec`
  - `wall_beam.side_wall_beam_section_spec`
  - `wall_beam.end_wall_beam_section_spec`
- `end_wall_purlin_section`截面按照 `max(span(sorted_y_lines))` 从下表选取
<6.0m：C120×50×20×2.5
<7.5m：C140×50×20×2.5
<=9.0m：C160×60×20×2.5
- 默认:
  - `roof_purlin_spacing = 1.5`
  - `side_wall_purlin_spacing = 1.5`
  - `end_wall_purlin_spacing = 1.5`
  - `roof_purlin_section=LT1`
  - `side_wall_purlin_section=QLT1`
  - `end_wall_purlin_section=QLT1`
  - `roof_purlin_spacing/side_wall_purlin_spacing/end_wall_purlin_spacing=1.5`
- `roof_tie_bar_sections/side_wall_tie_bar_sections/end_wall_tie_bar_sections` 默认 `["CG1","XLT1","LTC1"]`.
- `purlin_section_table` 至少包含 `CG1/XLT1/LTC1` 及本步骤实际引用到的 `LT*/QLT*`;材料默认 `Q235B`.
- `roof_purlin_section/side_wall_purlin_section/end_wall_purlin_section` 与三类拉条截面必须在 `purlin_section_table` 中定义.

## 14. panel_system 子系统
### 屋面板边界序列
- `roof_panel_boundary_sequences` 必须为二维数组;每块面板用 4 个角点,单块也必须写成二维数组.
- **角点定位格式**:`X-Y-ROOF` ROOF 为固定标识,表示屋面标高.示例:`"1-A-ROOF"` 表示 X=1轴,Y=A轴.
- 双坡单屋脊:输出 2 块;单坡/平屋面:输出 1 块;多屋脊时,每坡一块,分界在屋脊位置,坡底交汇位置与檐口位置.
- 每块屋面板 4 点沿边界闭合一圈(顺/逆时针皆可);角点通过XY主轴线交点定位水平位置.
### 墙面板边界序列
- `wall_panel_boundary_sequences` 必须为二维数组;每块墙面用 4 个角点.
- 角点标高为 FLn(楼层标高) 或 ROOF(屋面标高).
- 山墙/侧墙按墙面分块输出,每块为4点闭合序列,要注意单坡,双坡单屋脊与双坡多屋脊的屋脊位置.
- 多屋脊时,以双坡四跨双屋脊为例,每面山墙要包含四个面板,也就是四组的四点序列;
### 矮墙规则
- `short_wall_type` 默认"钢混矮墙".
- 若用户明确"无矮墙/不要矮墙/墙板落地",`short_wall_ranges` 为空数组.
- 否则必须包含外墙一圈:两侧边墙 + 两端山墙.
  - **矮墙定位格式**:`X1:X2-Y-0:<高度>@<厚度>` 或 `X-Y1:Y2-0:<高度>@<厚度>`(单位 m).
  - 示例:`"1:10-A-0:0.6@0.2"` 表示 1-10轴区间,A轴侧,0到0.6m高,厚0.2m.
  - 默认高度 0.6,厚度 0.2~0.24.

## 15. opening_aux_axis 子系统
- 门窗需求为空或未提供时,门窗系统辅助轴线与门窗系统全部输出空对象

## 16. opening_system 子系统
### 门窗输出流程(有需求时执行)
**目标**:先定义门窗辅助轴线,再用定位格式精确描述开洞位置.
**"开间"概念解释**:开间表示两榀相邻门架之间的区域,即 X 主轴线相邻坐标中间的区域.
1) **轴线清单**:X 取 `x_main_axis_coors` 的键;Y 取 `y_main_axis_coors` 的键 + `y_wind_column_aux_axes` 的键;Z 取 `z_main_axis_coors` 的键.
2) **门窗辅助轴线**:在主轴线之间增加辅助轴线,表示门窗左右与上下边缘:
   - `x_opening_aux_axes`:键为 `XW1/XW2/...`,值为 X 坐标(m),必须位于相邻主轴线之间.
   - `y_opening_aux_axes`:键为 `YW1/YW2/...`,值为 Y 坐标(m),必须位于相邻主轴线之间.
   - `z_opening_aux_axes`:键为 `ZW1/ZW2/...`,值为 Z 标高(m),必须位于 0~EAVE 之间.
   - 辅助轴线不得与已有主轴线或已存在的辅助轴线重合;若重合,必须复用已有轴线/辅助轴线,禁止重复新增.
   - 若门窗边缘与主轴线/已存在 Z 轴线重合,可直接使用主轴线/标高名,不必新增辅助轴线;此时对应 x_opening_aux_axes/y_opening_aux_axes/z_opening_aux_axes 允许为空.
3) **定位格式**(使用本步骤定位规则):
   - 侧墙门/窗:`X左:X右-Y-Z下:Z上`
   - 山墙门/窗:`X-Y左:Y右-Z下:Z上`
   - **IMPORTANT**:单个门窗对象位置范围**禁止跨越任何主轴线与梁柱系统辅助轴线**;若跨越必须拆分为多个洞口或调整到单一轴线区间内.
4) **截面格式**:
   - 门框:`<MZ*>-<ML*>`
   - 窗框:`<CZ*>-<CL*>-<CL*>`
5) **对象条目统一格式**:`"<区间>":"<截面>"`(字符串),并按下列字段输出:
   - `x_side_door`:侧墙门
   - `y_end_door`:山墙门
   - `x_side_window`:侧墙窗
   - `y_end_window`:山墙窗
6) **几何一致性**:同区间窗底标高必须 > 门框顶标高;门窗与支撑冲突时优先保留支撑并调整门窗区间.
7) **需求缺失处理**:门窗需求为空则辅助轴线与四个门窗对象均为 `{}`,`door_window_section_table` 为空对象.
8) **一一对应**:门/窗对象中每个条目都必须在 `door_window_section_table` 中找到对应的 MZ/ML/CZ/CL 定义.
9) **门窗位置与其他构件冲突时约束**:门窗禁止设置在`roof_horizontal_bracing_sections`所在的开间(X区间),同时尽可能满足用户当前需求.doorPosition的要求.
### 门窗截面表
- `door_window_section_table` 的键仅允许 MZ/ML/CZ/CL 系列,编号从 1 起连续.
- MZ/ML/CZ/CL 必须全部在 `door_window_section_table` 中定义,且与门窗区间一一对应.
- MZ/ML 截面若未在 `column_section_table`/`beam_section_table` 中出现,最终合并时需同步写入 GZ/GL 截面表(编号从 1 起连续).
- `door_window_section_table` 默认使用方管或 C 型钢,避免 H 型钢.
- 默认材料 Q235B,note 标注用途(门柱/门梁/窗柱/窗台梁/窗顶梁).
### 额外约束
- 门窗对象条目必须是 `"<区间>":"<截面>"`,且与 `door_window_section_table` 一一对应.
- 门窗尺寸通过`opening_aux_axis`辅助轴线区间确定,禁止使用 `@宽` 表示洞口尺寸.
### 定位格式示例
- 面板角点:
```json
"roof_panel_boundary_sequences": [
  ["1-A-ROOF", "10-A-ROOF", "10-B-ROOF", "1-B-ROOF"],
  ["1-B-ROOF", "10-B-ROOF", "10-C-ROOF", "1-C-ROOF"]
]
```
- 门窗定位:
```json
"x_opening_aux_axes": {"XW1": 2.6, "XW2": 3.4},
"z_opening_aux_axes": {"ZW1": 0, "ZW2": 3.6, "ZW3": 3.8, "ZW4": 6.2},
"x_side_door": {"XW1:XW2-A-ZW1:ZW2":"MZ1-ML1"},
"x_side_window": {"XW1:XW2-A-ZW3:ZW4":"CZ1-CL1-CL2"}
```

## 17. skylight_system 子系统
- 如果解析用户需求不需要设置天窗:`skylight_positions` 与 `skylight_material` 为空对象.
- 否则:
  - skylight_positions 格式:{"ZQC1":[x1,y1,x2,y2],...}.
  - skylight_material 需与类型匹配(PMMA/PC/FRP/安全玻璃).

## 18. canopy_system 子系统
- 如果解析用户需求不需要设置雨棚:`canopy_positions` 为空对象;其余字段保持默认值.
- 否则:
  - 雨篷必须在门窗确定后配置,优先覆盖门洞上方.
  - **雨篷定位格式**:`X1:X2-Y-<根部标高>@<深度>`,示例:`"2:4-A-4.5@2.5"`(2-4轴区间,A轴侧,根部标高4.5m,深度2.5m).
  - `canopy_positions` 键为定位格式,值为 `"YP*-YLT*-XG*"`(雨篷梁-拉杆/支撑-端部系杆).
  - 深度 0.8~6m,坡度分母 30~50,支撑角度 30°~60°.
  - 雨篷根部高度不得与门窗洞口冲突.
  - `canopy_section_table` 至少包含 YP(雨篷梁) 与 YLT(拉杆/支撑) 的截面与材料.
  - 构件选型建议:深度<2.5m 用 H200×100×6×8;2.5~4m 用 H250×125×6×9;>4m 用 H300×150×6.5×9;拉杆/支撑深度<2.5m 用 φ16,2.5~4m 用 φ20,>4m 用 φ25 或角钢.
## 4) 额外约束
- `canopy_slope_direction` 仅允许 "向下倾斜"/"向上倾斜";`canopy_support_form` 必须为 "上拉式@角度°" 或 "下撑式@角度°".
- 两个系统字段必须齐全,缺失时输出空对象/默认值.
- 雨篷定位中的 `X*`/`Y*` 仅允许来自主轴线(`x_main_axis_coors/y_main_axis_coors`)或已声明的抗风柱辅助轴线及门窗辅助轴线(`x_opening_aux_axes/y_opening_aux_axes`).
- 本步骤通常不直接使用 `EAVE` 作为定位键;若需要引用屋面檐口标高,应取 `z_main_axis_coors.EAVE` 对应数值.
- 雨篷根部标高与深度均使用 m 数值.
- 禁止新增与天窗/雨篷无关的定位表达或字段.
</schema_rules>