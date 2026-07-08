# chatbi-report 图表集成实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 Markdown 报表样张中读取 `> 图表:` 配置，生成图表 PNG 并嵌入到 DOCX 报表。

**Architecture:** 在现有 pipeline 基础上新增图表支持：parse_md.py 解析图表配置 → pipeline.py 调用 chart_gen.py → render_docx.py 嵌入图表图片。

**Tech Stack:** Python, python-docx, matplotlib

---

## 文件结构

| 文件 | 改动 |
|------|------|
| `scripts/parse_md.py` | 新增 ChartSpec dataclass + `_parse_chart_blocks()` |
| `scripts/chart_gen.py` | 新增翻译层 `_translate_spec()` 适配中文字段 |
| `scripts/pipeline.py` | Phase1 新增 chart_gen 调用，Phase2 传入 chart_manifest |
| `scripts/render_docx.py` | 新增 `_embed_chart()` 函数嵌入图片 |

---

## 任务分解

### Task 1: parse_md.py 新增图表解析

**Files:**
- Modify: `/Users/raidery/.pi/agent/skills/chatbi-report/scripts/parse_md.py`

- [ ] **Step 1: 新增 ChartSpec dataclass**

在 `ComputedSpec` dataclass 后添加：

```python
@dataclass
class ChartSpec:
    标题: str
    类型: str           # bar | line | pie | bar_line
    x轴: str
    y轴: list[str] | None = None          # 单轴图
    y轴左: list[str] | None = None        # bar_line
    y轴右: list[str] | None = None        # bar_line
    系列: str | None = None               # 行社 | 指标 (line 图用)
    单位: str | None = None               # 单轴图
    左轴单位: str | None = None
    右轴单位: str | None = None
    条形配色: list[str] | None = None     # ["#3498db", "#2ecc71"]
    折线配色: list[str] | None = None     # ["#e74c3c", "#f39c12"]
    输出: str | None = None              # slug

    def to_dict(self) -> dict:
        d = {"标题": self.标题, "类型": self.类型, "x轴": self.x轴}
        if self.y轴 is not None:
            d["y轴"] = self.y轴
        if self.y轴左 is not None:
            d["y轴左"] = self.y轴左
        if self.y轴右 is not None:
            d["y轴右"] = self.y轴右
        if self.系列 is not None:
            d["系列"] = self.系列
        if self.单位 is not None:
            d["单位"] = self.单位
        if self.左轴单位 is not None:
            d["左轴单位"] = self.左轴单位
        if self.右轴单位 is not None:
            d["右轴单位"] = self.右轴单位
        if self.条形配色 is not None:
            d["条形配色"] = self.条形配色
        if self.折线配色 is not None:
            d["折线配色"] = self.折线配色
        if self.输出 is not None:
            d["输出"] = self.输出
        return d
```

- [ ] **Step 2: 新增 Report.chart_specs 字段**

修改 `Report` dataclass，在 `description_prompt` 后添加：

```python
chart_specs: list[ChartSpec] = field(default_factory=list)
```

修改 `Report.to_dict()`，添加：

```python
"chart_specs": [c.to_dict() for c in self.chart_specs],
```

- [ ] **Step 3: 新增 `_split_chart_value()` 辅助函数**

```python
def _split_chart_value(value: str | None) -> list[str] | None:
    """将逗号分隔的字符串转为列表，或返回 None"""
    if value is None:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]
```

- [ ] **Step 4: 新增 `_parse_chart_blocks()` 函数**

在 `_parse_description_block()` 后添加：

```python
def _parse_chart_blocks(body: str) -> list[ChartSpec]:
    """解析 > 图表: 块，返回 ChartSpec 列表"""
    results: list[ChartSpec] = []
    # 查找所有 > 图表: 块
    pattern = re.compile(r"^>\s*图表:\s*$", re.MULTILINE)
    for match in pattern.finditer(body):
        start = match.end()
        # 收集缩进的 key: value 行
        block_lines: list[str] = []
        for line in body[start:].splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # 遇到非缩进 > 行（如 > 描述:）或表格，停止
            if re.match(r"^>\s?\S", line) and not re.match(r"^>\s{2,}\S", line):
                break
            if stripped.startswith("<"):
                break
            block_lines.append(stripped)
        
        # 解析 block_lines 为 dict
        chart_dict: dict[str, str | None] = {}
        for line in block_lines:
            if ": " in line:
                key, value = line.split(": ", 1)
                chart_dict[key.strip()] = value.strip()
            elif ":" in line:
                key, value = line.split(":", 1)
                chart_dict[key.strip()] = value.strip()
        
        # 转换为 ChartSpec
        required_fields = ["标题", "类型", "x轴"]
        for field in required_fields:
            if field not in chart_dict:
                raise ValueError(f"图表配置缺少必需字段: {field}")
        
        spec = ChartSpec(
            标题=chart_dict.get("标题", ""),
            类型=chart_dict.get("类型", ""),
            x轴=chart_dict.get("x轴", ""),
            y轴=_split_chart_value(chart_dict.get("y轴")),
            y轴左=_split_chart_value(chart_dict.get("y轴左")),
            y轴右=_split_chart_value(chart_dict.get("y轴右")),
            系列=chart_dict.get("系列"),
            单位=chart_dict.get("单位"),
            左轴单位=chart_dict.get("左轴单位"),
            右轴单位=chart_dict.get("右轴单位"),
            条形配色=_split_chart_value(chart_dict.get("条形配色")),
            折线配色=_split_chart_value(chart_dict.get("折线配色")),
            输出=chart_dict.get("输出"),
        )
        results.append(spec)
    
    return results
```

- [ ] **Step 5: 修改 `_parse_one_report()` 调用图表解析**

在 `_parse_one_report()` 函数中，`description_prompt = _parse_description_block(body)` 后添加：

```python
chart_specs = _parse_chart_blocks(body)
```

并修改 `Report()` 构造：

```python
return Report(
    title=report_title,
    org_contexts=org_contexts,
    time_info=time_info,
    headers=headers_2d,
    data_rows=data_rows,
    computed_specs=computed_specs,
    description_prompt=description_prompt,
    chart_specs=chart_specs,
)
```

- [ ] **Step 6: 测试 parse_md.py**

先把测试 fixture 复制到 `/tmp/chatbi-test/uploads/`：

```bash
mkdir -p /tmp/chatbi-test/uploads /tmp/chatbi-test/outputs
cp ~/bench/harness/raidery/deer-flow/skills/public/chatbi-report/example/input-bar-line-colors.md \
   /tmp/chatbi-test/uploads/
```

Run:
```bash
cd /Users/raidery/.pi/agent/skills/chatbi-report/scripts && python -c "
from parse_md import parse_file
parsed = parse_file('/tmp/chatbi-test/uploads/input-bar-line-colors.md')
for s in parsed.sections:
    for r in s.reports:
        print(f'Report: {r.title}')
        print(f'chart_specs: {len(r.chart_specs)}')
        if r.chart_specs:
            c = r.chart_specs[0]
            print(f'  标题: {c.标题}')
            print(f'  类型: {c.类型}')
            print(f'  x轴: {c.x轴}')
            print(f'  y轴左: {c.y轴左}')
            print(f'  条形配色: {c.条形配色}')
"
```

Expected:
```
Report: 1.1 贷款余额、存款净增与不良率综合分析
chart_specs: 1
  标题: 贷款余额、存款净增与不良率综合分析
  类型: bar_line
  x轴: 行社
  y轴左: ['贷款余额', '存款日均净增']
  条形配色: ['#3498db', '#2ecc71']
```

- [ ] **Step 7: 提交**

```bash
git add scripts/parse_md.py
git commit -m "feat(chart): parse_md.py 新增图表配置解析
- 新增 ChartSpec dataclass
- 新增 _parse_chart_blocks() 函数
- Report 新增 chart_specs 字段"
```

---

### Task 2: chart_gen.py 适配中文字段

**Files:**
- Modify: `/Users/raidery/.pi/agent/skills/chatbi-report/scripts/chart_gen.py`

- [ ] **Step 1: 新增翻译层函数**

在 `extract_series()` 函数前添加：

```python
def _split_list(value: str | list | None) -> list | None:
    """将逗号分隔的字符串转为列表，或直接返回列表/None"""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return None


def _translate_spec(spec: dict) -> dict:
    """翻译中文 chart_spec 到 chart_gen 期望的英文格式"""
    translated: dict = {
        "title": spec.get("标题"),
        "type": spec.get("类型"),
        "x": spec.get("x轴"),
        "y": _split_list(spec.get("y轴")),
        "y_left": _split_list(spec.get("y轴左")),
        "y_right": _split_list(spec.get("y轴右")),
        "series": spec.get("系列"),
        "unit": spec.get("单位"),
        "left_unit": spec.get("左轴单位"),
        "right_unit": spec.get("右轴单位"),
        "bar_colors": _split_list(spec.get("条形配色")),
        "line_colors": _split_list(spec.get("折线配色")),
        "output": spec.get("输出"),
    }
    # 移除 None 值
    return {k: v for k, v in translated.items() if v is not None}
```

- [ ] **Step 2: 修改 `generate_charts()` 在循环顶部翻译 spec**

⚠️ **关键**：必须在 `generate_charts()` 的内层循环顶部翻译 spec，**而不是** `extract_series()`。因为 `generate_charts()` 在调用 `extract_series()` **之前**就访问了 `spec.get("output")`、`spec["title"]`、`spec["type"]`、`spec.get("bar_colors")`、`spec.get("line_colors")`（chart_gen.py:546-563），这些字段全是英文 key。如果 spec 来自中文 `ChartSpec.to_dict()`，访问会 `KeyError`。

在 `generate_charts()` 内层循环顶部加一行翻译：

```python
def generate_charts(parsed, wide, out_dir, manifest_path, *, stem=None):
    ...
    for section_idx, sec in enumerate(parsed.get("sections", [])):
        for report_idx, report in enumerate(sec.get("reports", [])):
            report_entry = {"section_idx": section_idx, "report_idx": report_idx, "charts": []}
            wide_rows = _filter_wide_by_report(wide, section_idx, report_idx)
            chart_idx = 0
            for spec in report.get("chart_specs", []):
                # 中文 spec 翻译为英文 key，下游直接读取
                spec = _translate_spec(spec)
                slug = spec.get("output") or f"report-{section_idx}-{report_idx}-{chart_idx}"
                ...  # 其余代码不变
```

**不要**修改 `extract_series()` —— 它读 spec 的英文 key 即可，让上游负责翻译。

- [ ] **Step 3: 测试 chart_gen 翻译层**

Run:
```bash
cd /Users/raidery/.pi/agent/skills/chatbi-report/scripts && python -c "
from parse_md import parse_file
import json
parsed = parse_file('/tmp/chatbi-test/uploads/input-bar-line-colors.md')
r = parsed.sections[0].reports[0]
print('Original chart_specs:', json.dumps(r.chart_specs[0].to_dict(), ensure_ascii=False, indent=2))

from chart_gen import _translate_spec
translated = _translate_spec(r.chart_specs[0].to_dict())
print('Translated:', json.dumps(translated, ensure_ascii=False, indent=2))
"
```

Expected:
```
Translated: {
  "title": "贷款余额、存款净增与不良率综合分析",
  "type": "bar_line",
  "x": "行社",
  "y_left": ["贷款余额", "存款日均净增"],
  "y_right": ["不良率", "占比"],
  "left_unit": "万元",
  "right_unit": "%",
  "bar_colors": ["#3498db", "#2ecc71"],
  "line_colors": ["#e74c3c", "#f39c12"],
  "output": "loan-multi-combo-colors"
}
```

- [ ] **Step 4: 提交**

```bash
git add scripts/chart_gen.py
git commit -m "feat(chart): chart_gen.py 适配中文字段名
- 新增 _translate_spec() 翻译层
- generate_charts() 循环顶部调用翻译（覆盖 spec['title']/['type']/['bar_colors'] 等直接访问）"
```

---

### Task 3: pipeline.py 集成 chart_gen（Phase 2 run_phase_2 内 post-compute）

**Files:**
- Modify: `/Users/raidery/.pi/agent/skills/chatbi-report/scripts/pipeline.py`

**设计原则（Option A：与 description 解耦）**：

图表生成放在 `run_phase_2()` 中，**位置在 Step 8c（apply-computed）之后、Step 8d（attach-description）之前**。理由：

- 图表使用 post-compute `wide`（计算列已求值）
- `{{...}}` 计算列可在图表 `y轴` / `y轴左` / `y轴右` 中**自由引用**
- **与 description checkpoint 解耦**——description 缺失时 charts 仍然生成（charts 不依赖文本描述）
- **与 skip_docx 解耦**——`skip_docx=True` 时也生成 PNG（charts 写到磁盘作为 artifact）

`_finish_phase_2()` 只负责从磁盘读 chart_manifest 传给 `render_docx()`，不调 `generate_charts`。

> ⚠️ **历史决策记录**：早期版本曾把 charts 放在 `_finish_phase_2()`，导致 description 缺失时 charts 不生成——用户 2026-07-07 review 时纠正，改到 `run_phase_2()` Step 8d 之前。

- [ ] **Step 1: 保持 `Phase1Result` 不变（不加 chart_manifest）**

不要修改 `Phase1Result` dataclass。Phase 1 不生成图表，wire format 不包含 `chart_manifest` 字段。

- [ ] **Step 2: 不修改 `run_phase_1()`（Phase 1 不调 chart_gen）**

`run_phase_1()` 末尾不需要新增 Step 6.5。保持现有代码不变。

- [ ] **Step 3: 在 `run_phase_2()` 中 Step 8c 之后、Step 8d 之前调用 `generate_charts()`**

位置：在 `wide_path.write_text(...)`（line 293，持久化 post-compute wide）之后、`attach_description_files(doc, descriptions_dir, stem=stem)`（line 300）之前插入。

```python
# Step 8c.5: chart generation (post-compute, description-independent)
from chart_gen import generate_charts

chart_dir = self._cfg.out_dir / f"{stem}.charts"
chart_manifest_path = self._cfg.out_dir / f"{stem}.charts.json"
chart_manifest: dict | None = None
try:
    chart_manifest = generate_charts(
        parsed=parsed,
        wide=wide,  # post-compute wide, 计算列已求值
        out_dir=str(chart_dir),
        manifest_path=str(chart_manifest_path),
        stem=stem,
    )
    metrics["chart_gen"] = {
        "ok": chart_manifest["summary"]["ok"],
        "failed": chart_manifest["summary"]["failed"],
        "status": chart_manifest["summary"]["status"],
    }
except Exception as exc:
    # chart 生成失败不阻断后续步骤
    metrics["chart_gen"] = {"status": "ERROR", "error": str(exc)}
    chart_manifest = None
```

注意 `wide=wide`（post-compute，line 285 `apply_computed_results` 已修改 in-place），不是 `flat_wide`。

- [ ] **Step 4: 在 `_finish_phase_2()` 中从磁盘读 chart_manifest 传给 `render_docx()`**

`_finish_phase_2()` 不再调 `generate_charts()`，只读磁盘：

```python
# 加载 chart manifest（run_phase_2 Step 8c.5 写入）
chart_manifest: dict | None = None
chart_manifest_path = self._cfg.out_dir / f"{stem}.charts.json"
if chart_manifest_path.exists():
    chart_manifest = json.loads(chart_manifest_path.read_text(encoding="utf-8"))

# 即使 skip_docx=True 也允许 chart_manifest=None 正常传递（render_docx 会跳过）
render_docx(
    doc,
    wide_by_report,
    out_path=str(report_docx_path),
    style_path=str(resolved_style),
    chart_manifest=chart_manifest,
)
```

- [ ] **Step 5: 不修改 `_emit_wire_format()` 的 `Phase1Result` 分支**

`Phase1Result` 不变，`_emit_wire_format()` 也不变。chart_manifest 不出现在 Phase 1 wire format 中。

`RunResult`（Phase 2）现有 wire format 也无需改——`metrics["chart_gen"]` 已包含在 `RunResult.metrics` 中，自然出现在 Phase 2 wire format 的 `metrics` 字段里。

- [ ] **Step 6: 测试 Phase 1 + Phase 2 端到端**

Phase 1 不应有图表相关输出：

```bash
cd /Users/raidery/.pi/agent/skills/chatbi-report/scripts && python pipeline.py phase1 \
  --md /tmp/chatbi-test/uploads/input-bar-line-colors.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock
```

Expected：Phase 1 正常完成，**`out_dir/input-bar-line-colors.charts/` 目录不存在**（Phase 1 不写图表）。

然后跑 Phase 2（图表在这里生成）：

```bash
cd /Users/raidery/.pi/agent/skills/chatbi-report/scripts && python pipeline.py phase2 \
  --md /tmp/chatbi-test/uploads/input-bar-line-colors.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock

# 检查 PNG 文件
ls -la /tmp/chatbi-test/outputs/input-bar-line-colors.charts/
# 检查 manifest
cat /tmp/chatbi-test/outputs/input-bar-line-colors.charts.json | python -c "import sys,json; d=json.load(sys.stdin); print('summary:', d['summary'])"
```

Expected: PNG 文件存在 + `summary: {'ok': 1, 'failed': 0, 'skipped': 0, 'status': 'OK'}`。

- [ ] **Step 7: 提交**

```bash
git add scripts/pipeline.py
git commit -m "feat(chart): pipeline.py run_phase_2 集成 chart_gen (Step 8c.5)
- run_phase_2() Step 8c.5 调 generate_charts，使用 post-compute wide
- 与 description checkpoint 解耦（charts 不依赖 description）
- 与 skip_docx 解耦（PNG 总是生成）
- _finish_phase_2() 从磁盘读 chart_manifest 传给 render_docx()
- 计算列 {{...}} 可在图表 y轴 中引用"
```

---

### Task 4: render_docx.py 嵌入图表

**Files:**
- Modify: `/Users/raidery/.pi/agent/skills/chatbi-report/scripts/render_docx.py`

- [ ] **Step 1: 新增 `_embed_chart()` 函数**

在 `_add_styled_paragraph()` 函数后添加：

```python
def _embed_chart(docx, chart_path: str, width_cm: float = 15.0) -> None:
    """在 DOCX 中嵌入图表图片。"""
    try:
        p = docx.add_paragraph()
        run = p.add_run()
        run.add_picture(chart_path, width=Cm(width_cm))
    except FileNotFoundError:
        # 图片不存在时跳过（chart 生成失败但不影响 DOCX），但要 stderr 提示
        print(f"chart not found, skip embedding: {chart_path}", file=sys.stderr)
    except Exception as exc:
        # 其他错误（PNG 损坏、磁盘满、权限）记录但继续渲染 DOCX
        # —— 不要静默吞掉，否则 DOCX 看似完整实际少图
        print(f"failed to embed chart {chart_path}: {type(exc).__name__}: {exc}", file=sys.stderr)
```

⚠️ **不要**用 `except Exception: pass` —— 上面的初版会吞掉所有错误，连 PNG 损坏都看不到。至少要 `print(..., file=sys.stderr)`。

- [ ] **Step 2: 修改 `_render_report()` 添加图表参数**

修改函数签名：
```python
def _render_report(docx, report, wide_rows, style, chart_manifest: dict | None = None):
```

- [ ] **Step 3: 在 `_render_report()` 中插入图表**

在描述段落之后、表格之前添加：

```python
    # 描述段落
    description_text = getattr(report, "description_text", None)
    if description_text:
        _add_styled_paragraph(docx, str(description_text).strip(), style["font"]["body"])

    # 图表（纵向堆叠）
    if chart_manifest:
        for chart_info in chart_manifest.get("charts", []):
            if chart_info.get("status") == "ok" and chart_info.get("path"):
                _embed_chart(docx, chart_info["path"])

    # 表格
    if not wide_rows:
        ...
```

- [ ] **Step 4: 修改 `_render_section()` 传递 chart_manifest**

⚠️ **不能用 `ridx` 匹配 `section_idx`**。`ridx` 是跨 section 累加的全局 report 计数器，而 `chart_manifest["reports"][].section_idx` 是真实的 section 索引。直接用 `ridx` 匹配会导致：只有第一个 section 的前几个 report 能匹配上，后面的全部错位。

必须显式传入 `section_idx` 参数：

```python
def _render_section(
    docx, sec, wide_by_report, ridx, style,
    section_idx: int,
    chart_manifest: dict | None = None,
):
    ...
    for rep_idx, report in enumerate(sec.reports):
        # 获取该 report 的 chart manifest
        rep_chart_manifest = None
        if chart_manifest:
            for rep_entry in chart_manifest.get("reports", []):
                if rep_entry.get("section_idx") == section_idx and rep_entry.get("report_idx") == rep_idx:
                    rep_chart_manifest = rep_entry
                    break
        _render_report(
            docx, report,
            wide_by_report[ridx + rep_idx] if ridx + rep_idx < len(wide_by_report) else [],
            style,
            chart_manifest=rep_chart_manifest,
        )
```

- [ ] **Step 5: 修改 `render_docx()` 接收 chart_manifest 并传 `section_idx`**

修改函数签名：
```python
def render_docx(
    report_doc,
    wide_by_report: list[list[dict]],
    *,
    out_path: str,
    style_path: str,
    chart_manifest: dict | None = None,
) -> None:
```

主循环改为 `enumerate` 出 `sec_idx` 并传入 `_render_section()`：
```python
    ridx = 0
    for sec_idx, sec in enumerate(report_doc.sections):
        _render_section(docx, sec, wide_by_report, ridx, style, sec_idx, chart_manifest)
        ridx += len(sec.reports)
```

- [ ] **Step 6: 修改 `main()` CLI 接收 chart_manifest 参数**

```python
parser.add_argument("--chart-manifest", default=None)
```

在 `render_docx()` 调用时：
```python
chart_manifest = None
if args.chart_manifest:
    chart_manifest = json.loads(Path(args.chart_manifest).read_text(encoding="utf-8"))
render_docx(doc, wide, out_path=args.out, style_path=args.style, chart_manifest=chart_manifest)
```

- [ ] **Step 7: 测试 render_docx 嵌入图表（standalone CLI）**

⚠️ `charts.json` 由 Phase 2 生成。必须先跑 phase1 + phase2 拿到 manifest，再用 render_docx.py standalone 验证：

```bash
cd /Users/raidery/.pi/agent/skills/chatbi-report/scripts
python pipeline.py phase1 \
  --md /tmp/chatbi-test/uploads/input-bar-line-colors.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock

python pipeline.py phase2 \
  --md /tmp/chatbi-test/uploads/input-bar-line-colors.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock

# 现在 charts.json 已存在，可以 standalone 测试
python render_docx.py \
  --parsed /tmp/chatbi-test/outputs/input-bar-line-colors.parsed.json \
  --wide /tmp/chatbi-test/outputs/input-bar-line-colors.wide.json \
  --style ../example/style.json \
  --out /tmp/chatbi-test/outputs/report-with-chart.docx \
  --chart-manifest /tmp/chatbi-test/outputs/input-bar-line-colors.charts.json

echo "Exit code: $?"
ls -la /tmp/chatbi-test/outputs/report-with-chart.docx
```

- [ ] **Step 8: 提交**

```bash
git add scripts/render_docx.py
git commit -m "feat(chart): render_docx.py 嵌入图表图片
- 新增 _embed_chart() 函数
- 描述段落后、表格前插入图表
- 支持 chart_manifest 参数"
```

---

### Task 5: 端到端集成测试

**Files:**
- Test: 使用 example 目录下的所有带图表的模板

- [ ] **Step 1: 测试 input-bar-grouped.md (2个图表)**

```bash
cp ~/bench/harness/raidery/deer-flow/skills/public/chatbi-report/example/input-bar-grouped.md /tmp/chatbi-test/uploads/

cd /Users/raidery/.pi/agent/skills/chatbi-report/scripts
python pipeline.py phase1 \
  --md /tmp/chatbi-test/uploads/input-bar-grouped.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock

python pipeline.py phase2 \
  --md /tmp/chatbi-test/uploads/input-bar-grouped.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock

ls -la /tmp/chatbi-test/outputs/input-bar-grouped.charts/
cat /tmp/chatbi-test/outputs/input-bar-grouped.charts.json | python -c "import sys,json; d=json.load(sys.stdin); print('summary:', d['summary'])"
```

Expected: 2 个 PNG 文件 + `summary: {'ok': 2, 'failed': 0, 'skipped': 0, 'status': 'OK'}`

- [ ] **Step 2: 测试 input-line-trend.md (line 图)**

```bash
cp ~/bench/harness/raidery/deer-flow/skills/public/chatbi-report/example/input-line-trend.md /tmp/chatbi-test/uploads/

cd /Users/raidery/.pi/agent/skills/chatbi-report/scripts
python pipeline.py phase1 \
  --md /tmp/chatbi-test/uploads/input-line-trend.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock

python pipeline.py phase2 \
  --md /tmp/chatbi-test/uploads/input-line-trend.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock

ls -la /tmp/chatbi-test/outputs/input-line-trend.charts/
```

- [ ] **Step 3: 测试 input-pie-composition.md (pie 图)**

```bash
cp ~/bench/harness/raidery/deer-flow/skills/public/chatbi-report/example/input-pie-composition.md /tmp/chatbi-test/uploads/

cd /Users/raidery/.pi/agent/skills/chatbi-report/scripts
python pipeline.py phase1 \
  --md /tmp/chatbi-test/uploads/input-pie-composition.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock

python pipeline.py phase2 \
  --md /tmp/chatbi-test/uploads/input-pie-composition.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock

ls -la /tmp/chatbi-test/outputs/input-pie-composition.charts/
```

- [ ] **Step 4: 验证 input-01.md 无图表场景**

```bash
cp ~/bench/harness/raidery/deer-flow/skills/public/chatbi-report/example/input-01.md /tmp/chatbi-test/uploads/

cd /Users/raidery/.pi/agent/skills/chatbi-report/scripts
python pipeline.py phase1 \
  --md /tmp/chatbi-test/uploads/input-01.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock

python pipeline.py phase2 \
  --md /tmp/chatbi-test/uploads/input-01.md \
  --out-dir /tmp/chatbi-test/outputs \
  --mock

# Phase 2 仍然生成 manifest（charts 列表为空）
cat /tmp/chatbi-test/outputs/input-01.charts.json | python -c "import sys,json; d=json.load(sys.stdin); print('summary:', d['summary'])"
```

Expected: `summary: {'ok': 0, 'failed': 0, 'skipped': 0, 'status': 'NO_CHARTS'}`

- [ ] **Step 5: 验证 DOCX 实际嵌入图表**

⚠️ 上面的步骤只验证 PNG 文件 + manifest JSON，**不能**保证 DOCX 里真的有图片。必须回读 DOCX 验证嵌入：

```bash
python -c "
from docx import Document
import sys
doc = Document('/tmp/chatbi-test/outputs/input-bar-line-colors.report.docx')
ns = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
drawings = doc.element.body.findall(f'.//{ns}inline')
print(f'embedded pictures: {len(drawings)}')
assert len(drawings) >= 1, 'no chart embedded in DOCX'
"
```

Expected: `embedded pictures: 1`（input-bar-line-colors 单图）

如果 `drawings` 为 0 但 PNG 文件存在，问题在 `_render_section()` 的 chart_manifest 查找逻辑（参见 Task 4 Step 4 的 ⚠️ 标注——`ridx` vs `section_idx` 错位）。

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "test(chart): 端到端集成测试
- input-bar-grouped: 2个图表
- input-line-trend: line 图
- input-pie-composition: pie 图
- input-01: 无图表场景
- DOCX 回读验证嵌入"
```

---

## 任务顺序

1. **Task 1**: parse_md.py 新增图表解析
2. **Task 2**: chart_gen.py 适配中文字段
3. **Task 3**: pipeline.py 集成 chart_gen
4. **Task 4**: render_docx.py 嵌入图表
5. **Task 5**: 端到端集成测试

---

## 验证清单

- [ ] `input-bar-grouped.md`: 2 个 bar 图表纵向排列
- [ ] `input-bar-line-colors.md`: bar_line 双轴图表，颜色正确
- [ ] `input-line-trend.md`: line 图表
- [ ] `input-pie-composition.md`: pie 图表
- [ ] `input-01.md`: 无图表场景不报错
- [ ] DOCX 中图表在描述之后、表格之前
- [ ] DOCX 中多图表纵向堆叠
