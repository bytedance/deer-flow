# chatbi-report 重构 — Design Spec

**Date**: 2026-07-06
**Status**: Draft (awaiting user review)
**Owners**: chatbi-report skill maintainers
**Related memory**: [[chatbi-report-replaces-sqlbot-report]], [[chatbi-report-fail-fast-query]], [[chatbi-report-docx-stale]], [[no-skill-parallel-orchestrators]], [[cross-cutting-constraint-boundary-discipline]], [[ai-report-archived-lesson]], [[feedback-stay-focused-dont-propose-scope]], [[brainstorming-design-verify-with-code]], [[brainstorming-no-implement-without-approval]]

## Background

`skills/public/chatbi-report/` 当前的 9 步流水线(lint → parse → query → assemble-wide → extract-ir → codegen → validate → evaluate → apply-computed → describe → render)在 Deerflow 沙箱里跑出两个问题:

1. **不稳定**:错误诊断链路过长(每个步骤独立 `python` 子进程 + 中间 JSON 落盘),失败时常出现"看似无关"的错误(下游步骤拿到 None 或缺字段),根因被中间文件遮蔽。
2. **慢**:9~12 个 agent tool call + 9~12 次 sandbox 子进程 spawn,叠加 2 次 LLM 调用和 3 个 checkpoint。每次 tool call 引入 ~2s LLM 决策开销 + ~1.5s 子进程启动开销 = ~3.5s/步 × 10 步 = ~35s 的纯 plumbing 开销。

根本原因不是业务逻辑慢,是 **plumbing 形态与 Deerflow 沙箱约束不匹配**:Deerflow 的 lead agent 只能通过 `bash` 调脚本、不能注入 in-process Python 桥,而当前 9 步每步都是独立 `python` 脚本,导致每步都付一次"agent 决策 + 子进程 + JSON 落盘"成本。

之前的"绕路"方案(`_orchestrator/` 目录 + monkey-patch 注入)已按 [[no-skill-parallel-orchestrators]] memory 废弃,原因是没有 in-process 桥可用,注入的 hook 永远 `NotImplementedError`。

## Goals

1. **库函数 + 单一 Orchestrator 入口**。9 个 script 保留为 library(`import` 后调函数),但运行时只通过 `scripts/pipeline.py:Orchestrator` 串起来,不再每步独立 spawn 进程。
2. **9 步逻辑、3 个 checkpoint、2 个 LLM 边界全部保留**。这次重构不改业务行为,不改 checkpoint 数量,不并 LLM 调用。
3. **Phase 1 / Phase 2 拆分**。以 LLM 边界为切分点 —— Phase 1 = 步骤 1~6(纯 bash),Phase 2 = 步骤 8a~9(纯 bash),两个 LLM 步骤(7 codegen、8d describe)由 agent 在 Phase 之间手动执行。
4. **E2E 锚点**。新增 `tests/e2e_minimal.py`,用 `MockSQLBotClient` 走完 Phase 1 + Phase 2,断言所有产物文件存在 + `status.json` 无 `USER_ABORTED`。这是"完工 gating"—— 没有 E2E green 不算完成(对齐 [[ai-report-archived-lesson]] 的教训)。
5. **统一错误诊断**。所有非 checkpoint 失败走 Python 异常类(不再用 stderr `FAIL:` 字符串),checkpoint 命中走 `CheckpointSignal` dataclass,agent 拿到后自己决定 `ask_clarification` 措辞。
6. **消除 `--mock` / `--mock-fixture` 双 flag 冗余**(用户 2026-07-06 反馈)。改为单一 `--mock-fixture <path>`,有则 mock、无则 real。
7. **可观测性**。Orchestrator 内部集中 `metrics` dict(每步耗时 + 成功/失败计数),为后续单点优化提供数据基础。

## Non-Goals

- 不改 SQLBot wire format,不改 `query_report_info` 签名。
- 不改 `<th data-idx>` / `<th data-unit>` 模板契约。
- 不改 mock fixture 文件结构(`example/mock_sqlbot/profit_yoy.json`)。
- 不合并两个 LLM 调用(codegen + describe),不减少 checkpoint 数量。
- 不引入 `--local` / `--inproc` 旁路 —— Deerflow 沙箱是唯一运行时,YAGNI。
- 不改 `SKILL.md` frontmatter 描述 / 触发规则(只改 body 里的 step 命令)。
- 不动 `chart_gen.py` / `test_chart_gen.py` —— 保留作为未来 chart 集成的参考代码,不在本次重构范围内。
- 不保留 ai-report 任何代码(虽然 architecture 模式镜像 ai-report,但 chatbi-report 是 active skill,见 [[chatbi-report-replaces-sqlbot-report]])。
- 不补历史运行数据 / 不迁移用户已生成的报告文件。

## Architecture

### 状态机(对比当前)

当前 9 步 = 9~12 个 agent action(每步是独立 `python` 子进程,加 3 个 `ask_clarification` checkpoint):

```text
[agent]→bash lint→ask_clarification(1.5)→bash parse→bash query→
ask_clarification(3.5)→bash assemble→bash extract-ir→
[agent] LLM codegen →
[agent]→bash validate→bash evaluate→bash apply-computed→
[agent] LLM describe →
ask_clarification(8d.5)→bash render-markdown→bash render-docx→bash assemble_status
```

重构后 = 4 个 agent action(`run_phase_1` + LLM codegen + `run_phase_2` + 收尾回执),其中 2 个 `bash` tool call + 2 个 LLM call:

```text
[agent]→bash run_phase_1
       │  (内部:lint→parse→query→assemble→extract-ir,1.5/3.5 命中时抛 CheckpointSignal)
       │  产物:parsed.json, query.json, wide.json, ir.json
       ▼
[agent] 读 ir.json + description_prompts
       │  (LLM 写 compute 源码 + description 文件)
       ▼
[agent]→bash run_phase_2
       │  (内部:validate→evaluate→apply-computed→读 description→render→status,
       │   8d.5 命中时抛 CheckpointSignal)
       │  产物:report.md, report.docx, status.json
       ▼
[done]
```

checkpoint 数量保持 3(1.5 lint、3.5 query、8d.5 description),LLM 调用保持 2(7 codegen、8d describe)。

### Phase 边界(为什么必须分两段)

chatbi-report 当前的 9 步里,2 个 LLM 步骤(codegen、describe)是 agent-in-loop 的真正来源,也是 Phase 拆分的天然切分点:

- **Phase 1 = 步骤 1~6**(纯 bash,无 LLM)
- **Phase 1 ↔ Phase 2 之间 = Agent 读 `ir.json` + `description_prompts`,写 compute 源码 + description 文件**
- **Phase 2 = 步骤 8a~9**(纯 bash,不含 codegen LLM,含 description 文件读入)

为什么不合并成一次 run?
1. LLM 步骤需要外部 LLM API,sandbox 不给业务脚本暴露 LLM 能力。
2. 合并后 agent 失去"读完 IR 再决定 codegen 策略"的机会窗口(目前 codegen 是在 IR 写盘后才调起的)。
3. checkpoint 必须落在 Phase 内,不能跨 Phase(否则无法在 Phase 1 内部"lint 失败就停")。

### Orchestrator API(单一入口)

```python
# scripts/pipeline.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class OrchestratorConfig:
    """单次 run 的不可变配置。CLI 解析的最终产物。"""
    md_path: Path                  # 用户上传的 <file>.md(Phase 1 入口)
    out_dir: Path                  # 写 wide.json / ir.json / outputs 的目录
    mock_fixture: Path | None      # None = RealSQLBotClient;非 None = MockSQLBotClient
    skip_docx: bool = False
    style_path: Path | None = None

@dataclass
class CheckpointSignal:
    """Orchestrator 在 1.5 / 3.5 / 8d.5 抛出的信号。
    是个数据类,不是 callable —— Agent 拿到后自己决定怎么 ask_clarification。
    """
    step: str                     # "1.5" | "3.5" | "8d.5"
    metrics: dict[str, Any]       # 步骤的 metrics(n_err/n_warn 或 ok/total 等)
    artifacts: dict[str, Path]    # 已写盘的产物路径,Agent 可展示给用户
    message: str                  # 给用户看的中文一句话

@dataclass
class Phase1Result:
    parsed: dict                  # ReportDoc.to_dict()
    wide: dict                    # wide.json 内容
    ir: list[dict]                # ComputeIR.to_dict() 列表
    description_prompts: list[str]  # 每 report 的描述 prompt(Agent 据此生成 description)
    metrics: dict[str, Any]
    runlog: list[dict]
    artifacts: dict[str, Path]

@dataclass
class RunResult:
    report_md: Path
    report_docx: Path | None      # skip_docx=True 时为 None
    status_json: Path
    metrics: dict[str, Any]

class Orchestrator:
    def __init__(self, cfg: OrchestratorConfig, sqlbot: Any) -> None:
        """sqlbot 是 RealSQLBotClient 或 MockSQLBotClient 实例。
        构造时确定,运行时不切换 —— Phase 1 和 Phase 2 行为一致。
        """
        self._cfg = cfg
        self._sqlbot = sqlbot

    def run_phase_1(self) -> Phase1Result | CheckpointSignal:
        """跑 1→1.5→2→3→3.5→4→6。
        - 1.5 / 3.5 命中:返回 CheckpointSignal
        - 否则:返回 Phase1Result(产物已写盘)
        """

    def run_phase_2(
        self,
        parsed: dict,
        wide: dict,
        compute_sources: dict[str, str],   # {column_name: file_path}
        descriptions: dict[str, str],      # {report_idx: file_path}
    ) -> CheckpointSignal | RunResult:
        """跑 8a→8b→8c→8d(读 description 文件)→8d.5→9。
        - 8a / 8d 内部失败:列变 sentinel(⚠️COMPUTE_FAILED / ⚠️DESCRIPTION_FAILED),继续
        - 8d.5 命中:返回 CheckpointSignal
        - 9 完成:返回 RunResult
        """
```

### 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| Orchestrator 是不是 callable? | **不是,CheckpointSignal 是数据类** | Agent 拿到后自己决定怎么 ask_clarification,不绑死 agent 框架 |
| Phase 边界是函数边界还是协程? | **函数边界** | 不引入 asyncio,保持简单,测试时普通函数即可 |
| cfg + sqlbot 是构造参数? | **是** | 测试可注入 `MockSQLBotClient(fixture_path=...)`,生产注入 `RealSQLBotClient(base_url=...)` |
| `run_phase_1` 返回 `Phase1Result | CheckpointSignal`? | **是** | Agent 拿到返回值后类型分支处理,无需 try/except |
| 9 个 script 保留 CLI 入口? | **是**(保留 `main()`) | 沙箱里仍可单步调试(测试 / 排错),CLI 是二等公民,Orchestrator 是一等 |

### 9 个 script 的角色

所有 script 保持 `library` + `main(argv)` 双形态,本次重构不改它们的库函数,只确保 import 接口稳定:

| script | library 入口 | CLI 用途(沙箱单步调试) |
|---|---|---|
| `md_lint.py` | `lint_file(path)`, `lint_markdown(md)` | 沙箱里单跑 lint |
| `parse_md.py` | `parse_file(path)`, `parse_markdown(md)`, `parse_report(md, sec_idx, rep_idx)` | 单跑 parse |
| `sqlbot_client.py` | `RealSQLBotClient(base_url)`, `MockSQLBotClient(fixture_path)`, `query_from_parsed(parsed, client)` | 单跑 query |
| `compute.py` | `extract_compute_ir(report)`, `assemble_wide_table(per_idx, report)`, `validate_ast/source/smoke/example`, `evaluate_column`, `apply_computed_results(wide, computed)` | 单跑 compute 子步骤 |
| `unit_conversion.py` | `convert_unit(raw_value, data_unit) -> Decimal`, `SCALE_FACTOR` | 库,无 CLI |
| `render_markdown.py` | `render_markdown(doc, wide, compute_status)`, `doc_from_dict`, `normalize_wide_by_report`, `attach_description_files` | 单跑 markdown 渲染 |
| `render_docx.py` | `render_docx(report_doc, wide, *, out_path, style_path)` | 单跑 docx 渲染 |
| `assemble_status.py` | `write_status(out_path, *, exit_step, error_class, error_detail, outputs, metrics)` | 单跑 status 写盘 |
| `retry.py` | `exponential`, `retry` | 库,无 CLI |
| `chart_gen.py` | (本次不动) | 保留作为未来 chart 集成参考 |

### CLI 形态(沙箱永远走,无 `--mock` flag)

```bash
# 真实 SQLBot(默认)
python /mnt/skills/public/chatbi-report/scripts/pipeline.py \
  --md /mnt/user-data/uploads/<file>.md \
  --out-dir /mnt/user-data/outputs

# Mock(测试 / 无 SQLBOT_BASE_URL 时)
python /mnt/skills/public/chatbi-report/scripts/pipeline.py \
  --md /mnt/user-data/uploads/<file>.md \
  --out-dir /mnt/user-data/outputs \
  --mock-fixture /mnt/skills/public/chatbi-report/example/mock_sqlbot/profit_yoy.json
```

差异只有一行:`--mock-fixture` 存在 → `MockSQLBotClient(fixture)`;否则 `RealSQLBotClient()`(构造时读 `SQLBOT_BASE_URL`,缺失则 raise)。**不再有 `--mock` boolean flag**。

### 验证过的 dataclass 形状(codegraph 2026-07-06)

`parse_md.py` 和 `compute.py` 的 dataclass 字段是 spec 的事实基础,以下是从 codegraph 抓的当前定义(实施时直接 import,不要重新定义):

```python
# parse_md.py
@dataclass
class Th:
    text: str
    is_indicator: bool
    is_computed: bool
    idx_id: str | None = None
    data_unit: str | None = None
    period: str | None = None
    rowspan: int | None = None
    colspan: str | None = None

@dataclass
class OrgContext:
    branch_num: str
    branch_short_name: str

@dataclass
class ComputedSpec:
    name: str
    formula_repr: str
    example_inputs: list[Any] = field(default_factory=list)
    example_outputs: list[Any] = field(default_factory=list)

@dataclass
class Report:
    title: str
    org_contexts: list[OrgContext]
    time_info: list[str]
    headers: list[list[Th]]
    data_rows: list[dict] = field(default_factory=list)
    computed_specs: list[ComputedSpec] = field(default_factory=list)
    description_prompt: str | None = None

@dataclass
class Section:
    title: str
    reports: list[Report]

@dataclass
class ReportDoc:
    title: str
    sections: list[Section]
    all_idx_ids: set[str] = field(default_factory=set)

# compute.py
@dataclass
class ComputeIR:
    name: str
    formula_repr: str
    base_idx_ids: list[str] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    examples: list[dict] = field(default_factory=list)
```

## Phase 1 内部执行(库调用链)

```python
# Orchestrator.run_phase_1() 伪代码
def run_phase_1(self) -> Phase1Result | CheckpointSignal:
    metrics: dict[str, Any] = {}
    runlog: list[dict] = []
    artifacts: dict[str, Path] = {}

    # Step 1: lint
    lint_result = lint_file(self._cfg.md_path)
    metrics["1_lint"] = {"n_err": ..., "n_warn": ...}
    if lint_result.exit_code != 0 and self._user_must_decide:
        return CheckpointSignal("1.5", metrics, artifacts, "...")

    # Step 2: parse
    parsed = parse_file(self._cfg.md_path)
    artifacts["parsed"] = self._out("parsed.json")
    artifacts["parsed"].write_text(json.dumps(parsed.to_dict(), ...))
    metrics["2_parse"] = {"n_sec": ..., "n_rep": ..., "n_idx": ...}

    # Step 3: query
    query_payload = query_from_parsed(parsed.to_dict(), self._sqlbot)
    artifacts["query"] = self._out("query.json")
    artifacts["query"].write_text(json.dumps(query_payload, ...))
    ok, total = count_query_results(query_payload)
    metrics["3_query"] = {"ok": ok, "total": total}
    if any_failed(query_payload):  # 2026-06-27 政策反转:always trigger
        return CheckpointSignal("3.5", metrics, artifacts, "...")

    # Step 4: assemble-wide
    wide = assemble_wide_table(query_payload, parsed.to_dict())
    artifacts["wide"] = self._out("wide.json")
    artifacts["wide"].write_text(json.dumps(wide, ...))
    metrics["4_assemble"] = {"rows": ..., "cols": ...}

    # Step 6: extract-ir
    ir = [extract_compute_ir(r).to_dict() for r in parsed.sections[0].reports]
    artifacts["ir"] = self._out("ir.json")
    artifacts["ir"].write_text(json.dumps(ir, ...))
    metrics["6_ir"] = {"n": len(ir)}

    description_prompts = [r.description_prompt for r in parsed.sections[0].reports if r.description_prompt]
    return Phase1Result(
        parsed=parsed.to_dict(),
        wide=wide,
        ir=ir,
        description_prompts=description_prompts,
        metrics=metrics,
        runlog=runlog,
        artifacts=artifacts,
    )
```

## Phase 2 内部执行(库调用链)

```python
# Orchestrator.run_phase_2() 伪代码
def run_phase_2(self, parsed, wide, compute_sources, descriptions) -> CheckpointSignal | RunResult:
    metrics: dict[str, Any] = {}

    # Step 8a: validate(per compute source)
    for col_name, src_path in compute_sources.items():
        # validate_ast, validate_signature, run_smoke, run_example
        # 失败:标记 sentinel,继续
        metrics.setdefault("8a_validate", {"ok": 0, "total": 0})
        metrics["8a_validate"]["total"] += 1
        if validate(src_path, col_name, wide): metrics["8a_validate"]["ok"] += 1
        else: wide = mark_sentinel(wide, col_name, "⚠️COMPUTE_FAILED")

    # Step 8b: evaluate
    computed = {col_name: evaluate(src_path, col_name, wide) for col_name, src_path in compute_sources.items()}

    # Step 8c: apply-computed
    wide = apply_computed_results(wide, computed)

    # Step 8d: attach description files(Agent 已在 Phase 1/2 之间写好)
    wide = attach_description_files(wide, descriptions)

    # Step 8d.5: description checkpoint
    if any_description_failed(wide):
        return CheckpointSignal("8d.5", metrics, ..., "...")

    # Step 9: render
    report_md_path = self._out("report.md")
    render_markdown(parsed, wide, compute_status, out_path=report_md_path)
    report_docx_path = None
    if not self._cfg.skip_docx:
        report_docx_path = self._out("report.docx")
        render_docx(parsed, wide, out_path=report_docx_path, style_path=self._cfg.style_path)

    # Step 9: status
    status_path = self._out("status.json")
    write_status(status_path, exit_step="9", error_class=None, outputs={...}, metrics=metrics)
    return RunResult(report_md=report_md_path, report_docx=report_docx_path, status_json=status_path, metrics=metrics)
```

## 性能账(诚实)

**这不是性能重构,是稳定性 + 可观测性重构。** 速度是次要收益:

| 项 | 当前(9 步独立子进程) | 重构后(2 个 phase call) | 节省 |
|---|---|---|---|
| Agent tool call 开销(LLM 决策 ~2s/步) | 9~12 步 × 2s = ~20s | 2 步 × 2s = ~4s | ~16s |
| Sandbox 子进程 spawn(~1.5s/步) | 9~12 步 × 1.5s = ~15s | 2 步 × 1.5s = ~3s | ~12s |
| 中间 JSON 落盘/读盘 | ~5 次 | ~0 次(Phase 内部 in-process) | ~2.5s |
| LLM 调用本身 | 2 次 × 15~30s = ~45s | 2 次 × 15~30s = ~45s | 0(没动) |
| Checkpoint 等用户 | 3 次(人决定) | 3 次(人决定) | 0(没动) |
| 业务逻辑 | ~2s | ~2s | 0 |
| **总节省** | — | — | **~30s** |

如果一次 run 是 2~3 分钟,这是 **15~25% 速度提升**。能感受到,不是革命性的。

**省不掉的部分**(也是后续单独优化的抓手):
- LLM 调用 ~45s(占大头) —— 想提速需合并 codegen + describe 为一次 LLM 调用,本次不做。
- Checkpoint 等用户 —— 用户已明确拒绝减少(2026-07-06 反馈)。
- 业务逻辑 ~2s(本来就不是瓶颈)。

**真正的收益在别处**:
- 错误从"追 JSON"变"看 traceback"(统一异常类 + 集中 metrics)
- 状态机不再依赖外部文件一致性(dataclass 边界检查,字段漂移在 Phase 内部就抛)
- E2E 锚点能挡住回归(改 compute.py / parse_md.py 不再需要进 chat UI 跑真实 run)
- 后续单点优化有数据基础(集中 metrics 字典,定位"哪步最慢"不用猜)

## Testing strategy

### 测试金字塔

| 层级 | 数量 | 覆盖 | 责任 |
|---|---|---|---|
| E2E 锚点 | 1 | `tests/e2e_minimal.py` 走 Phase 1 + Phase 2 全状态机,断言所有产物 + status.json 无 `USER_ABORTED` | 完工 gating |
| 状态机单元(per-step) | 7 | 现有 `test_parse_md.py` / `test_md_lint.py` / `test_compute.py` 等 + 新增"步骤 N 命中时抛 CheckpointSignal" 断言 | 快速反馈 |
| sqlbot 注入 | 2 | `RealSQLBotClient` vs `MockSQLBotClient` 同输入同输出(扩展现有 `test_sqlbot_client.py`) | 注入路径正确 |
| 库函数 | 已有 | `validate_ast` / `validate_signature` / `run_example` / `run_smoke` / `convert_unit` | 细节正确 |

### E2E 测试样例

```python
# scripts/tests/test_e2e_minimal.py
"""用 MockSQLBotClient + stub compute_sources + stub descriptions
走完 Phase 1 + Phase 2,断言所有产物文件存在 + status.json 无 USER_ABORTED。
"""
def test_e2e_minimal(tmp_path):
    fixture = Path(__file__).parents[1] / "example" / "mock_sqlbot" / "profit_yoy.json"
    input_md = Path(__file__).parents[1] / "example" / "input.md"

    # 直接调 library 准备 parsed(等价 Phase 1 步骤 1+2)
    cfg = OrchestratorConfig(
        md_path=input_md,
        out_dir=tmp_path,
        mock_fixture=fixture,
    )
    sqlbot = MockSQLBotClient(str(fixture))
    orch = Orchestrator(cfg, sqlbot)

    # Phase 1
    result = orch.run_phase_1()
    assert isinstance(result, Phase1Result)
    stem = input_md.stem
    assert (tmp_path / f"{stem}.wide.json").exists()
    assert (tmp_path / f"{stem}.ir.json").exists()

    # 模拟 Agent 在 Phase 1/2 之间的工作
    compute_sources = {}
    for ir_item in result.ir:
        src = tmp_path / f"{ir_item['name']}.py"
        src.write_text(
            "def stub(df):\n    return 0\n"
        )
        compute_sources[ir_item["name"]] = str(src)
    descriptions = {}
    for i, _ in enumerate(result.description_prompts):
        desc = tmp_path / f"desc-{i}.txt"
        desc.write_text("stub description")
        descriptions[str(i)] = str(desc)

    # Phase 2
    final = orch.run_phase_2(result.parsed, result.wide, compute_sources, descriptions)
    assert isinstance(final, RunResult)
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "report.docx").exists()
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["error_class"] != "USER_ABORTED"
```

## Migration / Rollout

### 阶段 0:本文档化(本次 spec 评审通过后)

- 用户 review spec
- 通过后进入 writing-plans 阶段

### 阶段 1:实施(由 writing-plans + executing-plans skill 推进)

1. 新建 `scripts/pipeline.py`,定义 `OrchestratorConfig` / `CheckpointSignal` / `Phase1Result` / `RunResult` / `Orchestrator`。
2. 9 个 script 的 `main(argv)` 保留(沙箱单步调试用),库函数 import 即可,不改库函数本身。
3. 写 `tests/e2e_minimal.py` E2E 锚点。
4. 扩展现有 per-step 单元测试,断言 CheckpointSignal 行为。
5. 更新 `SKILL.md` 把"Phase 1 / Phase 2"步骤形态写明,旧的 9 步命令保留作为 `## 调试` 附录(沙箱单步用)。
6. 更新 `references/pipeline.md` 反映 Phase 拆分 + 新 API。
7. 更新 `README.md` 反映新 CLI(`--mock-fixture` 单 flag)。
8. 更新 `template-troubleshooting.md` 反映新错误诊断路径。

### 阶段 2:验证(必须 green)

- `pytest scripts/tests/ -v` 全绿
- `pytest backend/tests/chatbi_report/ -v`(integration scenarios)全绿
- E2E `test_e2e_minimal.py` green

### 阶段 3:不在本次范围

- 合并两个 LLM 调用(codegen + describe)—— 等本次重构稳定后,单独立项。
- 加 LLM cache —— 等本次重构稳定后,单独立项。
- chart 集成 —— 保留 `chart_gen.py` / `test_chart_gen.py` 作为未来参考,本次不动。
- ai-report 集成 chatbi-report 库 —— 见 [[ai-report-new-skill-not-replacement]],ai-report 是独立 skill,不共享代码。

## Risks

| 风险 | 缓解 |
|---|---|
| Orchestrator 把太多状态塞进内存,大报表 OOM | Phase 1 内部步骤之间仍走 in-process dataclass 而非 dict;wide.json 写盘后即可释放中间变量(实施时再决定具体 GC 策略) |
| CheckpointSignal 被错误吞掉(agent 拿到后忘了 ask_clarification) | E2E 测试 + 类型注解强制 agent 处理两种返回值;在 SKILL.md 显式说明 |
| E2E 用 MockSQLBotClient 跑通 ≠ 真实 SQLBot 跑通 | `tests/test_sqlbot_client.py` 现有覆盖,本次扩展;真实 SQLBot 跑通靠 integration 场景测试 |
| 重构期间业务行为漂移 | 9 个 script 库函数不改;E2E 用 input.md + profit_yoy.json fixture,跑通后产物 hash 与重构前对比(若 hash 不一致,逐字段查 diff) |
| 用户拒绝 `--mock` flag 移除 | Goals #6 已明确移除 `--mock` boolean flag(用户 2026-07-06 反馈"其中一个就可以");如有反对需在 user review 阶段提,实施前不保留兼容层 |

## Open questions

1. **Orchestrator 内部步骤顺序**:6 extract-ir 之后,是否需要在 Phase 1 末尾做一次 schema check(wide 行列对齐 ir 列名)?目前没有;实施时再加。
2. **`Phase1Result.description_prompts` 聚合粒度**:是 per-report(每个 report 一个 prompt)还是 per-section?目前 spec 假设 per-report;实施时看 parse_md.py 实际形态再定。
3. **8d description 文件路径契约**:Agent 写入 description 文件后,路径是 `out_dir/desc-<i>.txt` 还是 `out_dir/descriptions/<i>.txt`?目前 spec 用前者;实施时看现有 description 写盘路径再定。
4. **`status.json` 写盘时机**:Phase 2 末尾写,还是 Phase 1 末尾就先写一份 partial?目前 spec 假设 Phase 2 末尾;实施时再看是否有"中断后恢复"需求。

以上 4 个 open question 都需要在 writing-plans 阶段定稿,本文档先标注。
