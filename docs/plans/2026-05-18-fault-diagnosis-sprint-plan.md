# 故障诊断智能体 Sprint 实施计划（双 Sprint 拆分）

> **来源设计文档**：[故障诊断智能体功能设计文档](./2026-05-18-fault-diagnosis-design.md)
> **范围**：基于设计文档拆分出的执行计划，覆盖 Sprint 目标、故事拆分、依赖、验收标准、风险与排期。
> **修订（vs. 初版）**：将"机泵 + 旋转机 + 往复机一次交付"拆为 S1（机泵端到端样板）+ S2（旋转机/往复机复制 + 真实数据接入）；重新估算 SP；明确 PDF 不作为承诺交付；补集成验收 Story。

---

## 0. 双 Sprint 概览

| Sprint | 周期 | 目标 | 承诺范围 |
| ---- | ---- | ---- | ---- |
| **S1** | 2 周 | **机泵端到端 MVP**：group 升级 + 三个子 agent config + 三个新脚本 + pump-fault-diagnosis skill 骨架 + `fault-diagnosis--pump` 完整 SOUL.md + Markdown 导出 + 集成冒烟 | Stories S1-1 ~ S1-9 |
| **S2** | 1 周 | **旋转机 / 往复机复制 + 真实数据接入 + PDF 落地**：vibration skill code 映射 + reciprocating skill 骨架 + 两个子 agent SOUL.md + 历史故障案例库接入 + sandbox weasyprint 镜像更新 + 测试补全 | Stories S2-1 ~ S2-7 |

> **拆分理由**：原计划「2 周 / 26 SP / 三子 agent 全交付」与可承诺容量 14 SP 严重不匹配；机泵作为参考样板有真实价值，旋转机 / 往复机 SOUL.md 90% 复用机泵骨架，强行同 Sprint 交付反而牺牲机泵的工程质量。

---

## 1. Sprint S1：机泵端到端 MVP

### 1.1 Sprint Goal

在不新增后端路由、不新增前端组件的前提下，把 `fault-diagnosis` 升级为 group，交付机泵子 agent 的端到端诊断 MVP：用户可通过三轮 GenUI 表单（诊断范围 / 设备测点 / 故障家族焦点）触发 InS 工具链 + 规则 skill 生成结构化诊断报告，并支持 Markdown 导出（PDF 走 weasyprint 自动降级路径，sandbox 镜像更新前不可用）。其余两个子 agent（旋转机 / 往复机）仅占位 config 与 placeholder SOUL，菜单可见但提示「S2 上线」。

### 1.2 Sprint 假设

| 项 | 假设 |
| ---- | ---- |
| Sprint 周期 | 2 周 |
| 团队配置 | 1 名全栈/Agent 工程师 + 0.5 名领域专家（规则评审 + 故障 code 评审） |
| 可用容量 | 10 人天（含领域专家 5 人天） |
| 工程师承诺容量 | 8 人天 ≈ 14 SP（按日报 Sprint 同口径 1 人天 ≈ 1.75 SP） |
| 领域专家承诺容量 | 4 人天（评审 + 占位规则 + code 映射） |
| Must 承诺 | Stories S1-1 ~ S1-9 共 14 SP |
| 不承诺 | PDF 实际可用、真实历史故障案例库、旋转机 / 往复机完整 SOUL.md |

### 1.3 Stories（S1）

#### Story S1-1（Must · 2 SP）：升级 fault-diagnosis 为 group + 四份 config.yaml

**目标**：菜单结构与 `ai-report` 一致，前端能正确发现 group + 三子 agent。

**范围**：

- 修改 `agents/builtin/fault-diagnosis/config.yaml`：增 `type: group`，调整 `description` / `tags`；`order` 保持现值或按产品决定。
- 把现有 `fault-diagnosis/SOUL.md` 改为"group 落地页"：渲染 `markdown` 引导用户进入子 agent。
- 新建 `agents/builtin/fault-diagnosis--pump/config.yaml`、`fault-diagnosis--rotating/config.yaml`、`fault-diagnosis--reciprocating/config.yaml`，按设计文档 §3 装配 skill 列表。
- 旋转机 / 往复机暂用 placeholder SOUL（"S2 上线，敬请期待"），不阻塞菜单可见性。

**验收**：

- 前端 `故障诊断` group 节点下出现 3 个子 agent。
- 进入旋转机 / 往复机子 agent 显示 placeholder 文案，不报错。
- 进入 group 父节点显示引导文案（不能继续会话）。
- 旧 fault-diagnosis thread 历史可只读访问。

**依赖**：无。

#### Story S1-2（Must · 1 SP）：领域专家评审故障家族 code 表

**目标**：锁定设计文档 §4.4 三类设备故障 code 列表，并补 vibration skill 中文 → code 的映射。

**范围**（领域专家 + 工程师）：

- 评审 §4.4 机泵 8 项 / 旋转机 12 项 / 往复机 11 项 code，对名称冲突或缺漏出报告。
- 在 `vibration-fault-diagnosis/SKILL.md` 末尾追加一段 "Fault family code mapping"：每行 `<中文家族名> → <code>`，覆盖 references 全部章节。
- 工程师把评审结论同步进设计文档（如有变更）。

**验收**：

- code 映射段已落入 vibration-fault-diagnosis/SKILL.md。
- 三类 code 列表无冲突；评审记录写入 `docs/plans/2026-05-18-fault-diagnosis-design.md` §4.4 顶部 changelog。

**依赖**：无（不依赖 Story S1-5 解析器实现）。

#### Story S1-3（Must · 1.5 SP）：pump-fault-diagnosis skill 骨架 + ≥3 条占位规则

**目标**：建立机泵规则 skill 骨架，至少 3 条可被解析器识别的占位规则用于端到端联调。

**范围**：

- 新建 `skills/custom/pump-fault-diagnosis/SKILL.md`（角色 / 工作流程 / 规则匹配指南 / 输出模板 / references 链接，对齐 vibration skill 风格）。
- 新建 `skills/custom/pump-fault-diagnosis/references/diagnosis-rules.md`：按设计文档 §6.1 给章节骨架；在不平衡 / 汽蚀 / 流量低于最小连续流量三章节各写 1 条占位规则。
- SKILL.md 头部声明"用户提供版本号 / 修订日期"，明确不替代 OEM 标准。

**验收**：

- skill 可被 `fault-diagnosis--pump/config.yaml` 加载。
- references/diagnosis-rules.md 章节骨架与设计文档 §6.1 一致。
- 至少 3 条规则文本能被 Story S1-5 解析器识别（联调验证）。

**依赖**：S1-2 code 表锁定。

#### Story S1-4（Must · 5 SP）：query_diagnosis.py（仅第一阶段聚合拉取）

**目标**：稳定的趋势特征批量查询脚本，InS 不可用时回退演示数据。

**范围**：

- 新增 `skills/custom/data-analyst/scripts/query_diagnosis.py`。
- 支持 `--kind` / `--equipment` / `--start` / `--end` / `--mode` / `--compare` / `--output`。
- 内部通过 `subprocess` 调用 `bash /mnt/skills/custom/ins-extract-trend-features/scripts/run.sh`，按 `--kind` 选默认特征列表（设计文档 §5.1）。
- **不调用** waveform / spectrum / orbit 相关 ins-* skill（这是 LLM 第二阶段职责）。
- InS 失败 / 超时（5s + 1 次重试） / `--equipment` 命中 demo 名单时，写演示数据，标记 `data_source=demo_fallback`，错误堆栈进 `warnings[]`。
- `process_signals` 字段（流量 / 压力 / 电流 / 温度）按 `--kind` 裁剪。
- 输出 JSON 与设计文档 §7.1 一致；`screening` 模式仅缩样不改字段。

**验收**：

- sandbox 中执行成功，输出文件路径正确。
- demo_fallback 路径不依赖 InS。
- `--mode screening` / `oneoff` 字段一致。
- `--compare none` / `previous_period` 都覆盖。
- 错误为结构化 JSON，无 stack trace 抛出。
- `process_signals` 按 `--kind=centrifugal_pump` 包含流量 + 入/出口压力 + 电机电流。

**依赖**：sandbox `python3` 与 `ins-extract-trend-features` skill 已部署。

#### Story S1-5（Must · 5 SP）：diagnosis_features.py + 规则解析器

**目标**：把 `query_diagnosis.json` + LLM 第二阶段 spectrum/orbit 中间结果转为 ECharts option + 规则匹配候选。

**范围**：

- 新增 `skills/custom/data-analyst/scripts/diagnosis_features.py`。
- 支持 `--input` / `--focus` / `--rules-skill` / `--output`。
- 实现轻量规则解析器：按 `--rules-skill` 加载对应 `references/diagnosis-rules.md`，按设备类型 / 故障家族章节切分，best-effort 关键词 + 阈值匹配，输出 `rule_matches[]` 候选。**不替代 LLM 推理**。
- 读取 `/mnt/user-data/outputs/spectrum_*.json` / `orbit_*.json`（如存在），按设备 ID 拼接到 `spectrum_charts[]` / `orbit_charts[]`。
- 输出 `equipment_summary` / `evidence_chain`（含 `verdict ∈ {exceed, marginal, normal}`，`marginal` 不进主诊断证据）/ `trend_chart` / `spectrum_charts[]` / `orbit_charts[]` / `rule_matches[]` / `historical_cases[]`（演示数据 0-3 条 + `data_source` 标记）/ `recommendations`，与设计文档 §7.2 一致。
- 规则解析失败时返回 JSON `{"warnings": [...], "rule_matches": []}`，不阻塞链路。

**验收**：

- 命令独立可运行，三类 `--rules-skill` 输入都能产出非空 `rule_matches[]`。
- ECharts option 可直接传给前端 `echart` Block 不抛 schema 错误。
- `rule_matches[].supporting_evidence_indices` 引用 `evidence_chain` 下标准确。
- 规则文件缺失时降级而非崩溃。

**依赖**：S1-4。

#### Story S1-6（Must · 2 SP）：export_diagnosis_report.py + 复用核验

**目标**：交付 in-process 调用的导出 API，PDF 自动降级路径就位。

**范围**：

- **前置任务（编码前必做）**：grep `export_report.py` 确认 `trend_chart_to_svg` / `_markdown_to_html` / `_write_pdf` / `build_export_result` 都存在并签名稳定。如发现私有函数需提升为公共 API，先在 `export_report.py` 中改名（去下划线 + 加文档注释），日报 SOUL 同步更新；不在 `export_diagnosis_report.py` 内复制实现。
- 新增 `skills/custom/data-analyst/scripts/export_diagnosis_report.py`。
- 实现 `render_diagnosis_markdown(payload, thread_id)` + `write_diagnosis_report(payload, fmt)`，与 `export_report.write_report` 同构。
- CLI 入口仅供本地测试 / 冒烟用，主要被 SOUL 通过 in-process import 调用（设计文档 §4.5 步骤 6）。
- PDF 走 `_write_pdf`；`ImportError` 不在脚本内吞掉，由 SOUL 捕获后追加"PDF 不可用"说明。
- 趋势 / 频谱 / 轨迹 SVG > 50KB 时落盘并以 artifact URL 引用。

**验收**：

- in-process 调用 `render_diagnosis_markdown` 返回 6 节模板完整 Markdown。
- `write_diagnosis_report(payload, "md")` 总成功，文件位于 `/mnt/user-data/outputs/`。
- `write_diagnosis_report(payload, "pdf")` 在当前 sandbox 抛 ImportError，调用方捕获后流程不中断。
- CLI `--format md` / `--format pdf` 二者都不抛 stack trace。
- `export_report.py` 的复用符号有正式公共 API 记录（去下划线或保留并加文档）。

**依赖**：S1-5；`export_report.py` 已存在。

#### Story S1-7（Must · 5 SP）：fault-diagnosis--pump SOUL.md 完整实现 + GenUI 联调

**目标**：以机泵作为三类设备的参考样板，落地三轮 GenUI 表单 + 第二阶段按需采样 + 诊断输出 + in-process 导出 + present_files 双文件。

**范围**：

- 新建 `agents/builtin/fault-diagnosis--pump/SOUL.md`，对齐 `ai-report--daily/SOUL.md` 风格。
- 实现设计文档 §4.1 共性骨架（核心原则、回调超时、payload 校验、严禁结构化摘要、严禁复用更早回调）。
- 实现 Round 1 / 1.5 / 2 三表单与对应 `fd-pump-*` 回调处理；Round 1 用 `date + hour-select` 拼时间窗。
- 实现 Round 3 第二阶段「按异常时间点稀疏调用 `ins-get-waveform-data` + `ins-extract-spectral-waveform-features` + `ins-get-orbit-data` + `ins-extract-orbit-centerline-features`」的 prompt 段落，明确分工边界。
- 实现 in-process 导出（`from export_diagnosis_report import ...`）+ `present_files` 双文件。
- Round 1.5 默认勾选 ≤5 台 + 显式注释「与日报全选惯例不同」。

**验收**：

- 三轮表单顺序触发，单轮中绝不渲染下一轮。
- 同线程二次诊断不复用旧回调 payload。
- LLM 输出无 `SESSION INTENT` / `SUMMARY` / `ARTIFACTS` / `NEXT STEPS` 字符串。
- `present_files` 不暴露 `query_diagnosis.json` / `diagnosis_features.json` / `spectrum_*.json` / `orbit_*.json`。
- PDF 不可用时报告末尾显示 `PDF 不可用（weasyprint 未安装）`。
- 第二阶段 ins 调用次数 ≤ 异常测点数 × 工具数（不会对所有测点调用）。

**依赖**：S1-1, S1-3, S1-4, S1-5, S1-6。

#### Story S1-8（Must · 1 SP）：集成冒烟（机泵端到端）

**目标**：父 group + 机泵子 agent + 占位旋转机/往复机入口一起跑通。

**范围**：

- 在 group 父节点 + 三个子节点之间切换，验证 callback_id 不串扰。
- 机泵子 agent 完整跑一次：scope → target → focus → 报告 → 双下载链接。
- 旋转机 / 往复机子 agent 进入显示 placeholder 文案，不抛错。
- 验证 `data_source=demo_fallback` 路径下 `historical_cases[]` 标"演示"前缀。

**验收**：

- 端到端冒烟脚本通过（可手动或 e2e 自动）。
- 截图归档至 `docs/plans/screenshots/2026-05-18-fault-diagnosis-pump-smoke/`。

**依赖**：S1-1, S1-7。

#### Story S1-9（Must · 0.5 SP）：S1 文档收尾

**目标**：Sprint 验收材料就位，向 S2 移交。

**范围**：

- 在设计文档 §4.4 顶部记录 code 评审 changelog（来自 S1-2）。
- 在 `pump-fault-diagnosis/references/diagnosis-rules.md` 顶部记录"占位规则版本号 + 待领域评审"。
- 撰写 S2 入口 Story 待办清单（写到本文件 §2 末尾）。

**验收**：

- Changelog 与待办清单已落盘。

**依赖**：S1-1 ~ S1-8。

### 1.4 S1 Sprint Sequencing

```text
Day 1
- S1-1：group + 四份 config（含旋转机/往复机 placeholder SOUL）
- S1-2：领域专家评审 code 表（并行）

Day 2
- S1-3：pump-fault-diagnosis skill 骨架 + ≥3 占位规则
- S1-4 起：query_diagnosis.py 演示数据路径

Day 3
- S1-4 完成：query_diagnosis.py InS 主路径 + 重试 + warnings + process_signals

Day 4
- S1-5 起：diagnosis_features.py 解析器 + 三类 rules-skill 加载

Day 5
- S1-5 完成：ECharts option + verdict 三态 + 联调 S1-3 占位规则

Day 6
- S1-6 前置：复用核验（grep + 必要的提升公共 API）
- S1-6：export_diagnosis_report.py + in-process API

Day 7
- S1-7 起：pump SOUL.md Round 1 / 1.5

Day 8
- S1-7：Round 2 / Round 3 第二阶段 prompt + in-process 导出

Day 9
- S1-8：集成冒烟 + 截图
- S1-9：文档收尾

Day 10
- 缓冲 + 临时阻塞处理
```

### 1.5 S1 Summary

```text
Sprint Goal:
机泵端到端 MVP：group + 机泵子 agent 完整诊断流程 + Markdown 导出 + 旋转机/往复机占位入口可见

Duration:
2 周

Capacity:
工程师 8 人天 ≈ 14 SP；领域专家 4 人天

Must Stories（共 14 SP）:
1. group + 四份 config — 2 SP
2. 领域专家评审 code 表 — 1 SP
3. pump-fault-diagnosis skill 骨架 + ≥3 占位规则 — 1.5 SP
4. query_diagnosis.py — 5 SP
5. diagnosis_features.py — 5 SP
6. export_diagnosis_report.py + 复用核验 — 2 SP
7. fault-diagnosis--pump SOUL.md + GenUI 联调 — 5 SP
8. 集成冒烟 — 1 SP
9. S1 文档收尾 — 0.5 SP

合计 23 SP > 14 SP 容量
→ 取舍：S1-2/S1-3/S1-9 由领域专家承担（不占工程师容量）；
        S1-1/S1-4/S1-5/S1-6/S1-7/S1-8 工程师承担合计 20 SP
        → 仍超容量，需要把 S1-7 拆成 S1-7a（Round 1/1.5/2 = 3 SP）+ S1-7b（Round 3 + 导出 = 2 SP）
        如果 S1-7b 来不及，作为 Should 推迟到 S2 Day 1

修正后工程师 Must 范围 ≈ 13 SP（S1-1/S1-4/S1-5/S1-6/S1-7a/S1-8），符合容量
S1-7b 列为 Should（必须 S2 之前完成，否则 S2 无样板可复制）

不承诺:
- 旋转机 / 往复机完整 SOUL.md
- PDF 实际可用（仅降级路径就位）
- 真实历史故障案例库
- vibration skill references 改造（vibration skill 仅追加 code 映射段）
- 单元测试完整覆盖（仅契约级 smoke）
```

---

## 2. Sprint S2：旋转机 / 往复机复制 + 真实数据接入 + PDF 落地

### 2.1 Sprint Goal

在 S1 机泵样板基础上：(a) 完成旋转机 / 往复机两个子 agent 的 SOUL.md，复用机泵 90% 骨架；(b) 接入真实历史故障案例库；(c) sandbox 镜像更新，使 PDF 实际可用；(d) 补单元测试与回归。

### 2.2 假设

| 项 | 假设 |
| ---- | ---- |
| Sprint 周期 | 1 周 |
| 工程师容量 | 5 人天 ≈ 8.75 SP，缓冲 20% 后 ≈ 7 SP 可承诺 |
| 领域专家 | 2 人天（往复机规则评审） |
| 前置 | S1-7b 已完成（机泵样板可复制） |

### 2.3 Stories（S2）

#### Story S2-1（Must · 1.5 SP）：reciprocating-fault-diagnosis skill 骨架 + ≥3 占位规则

**范围**：与 S1-3 同结构，覆盖吸气阀 / 活塞环磨损 / 十字头敲缸三章节各 1 条占位规则。SKILL.md 头部声明版本与日期。
**依赖**：S1 全部完成。

#### Story S2-2（Must · 2 SP）：fault-diagnosis--rotating SOUL.md + GenUI 联调

**范围**：复制机泵 SOUL，调整故障家族 code（旋转机 12 项），扩展默认勾选测点（两端轴振 + 轴位移 + 轴承/推力温度 + 转速 + 工艺联动），rules-skill 切到 `vibration-fault-diagnosis`。
**验收**：旋转机端到端冒烟通过；至少 1 条 vibration skill references 规则被命中。

#### Story S2-3（Must · 1.5 SP）：fault-diagnosis--reciprocating SOUL.md + GenUI 联调

**范围**：复制机泵 SOUL，去掉 orbit echart Block；证据链 `category` 增加 `crank_angle` / `cylinder_pressure` / `valve_event`；演示数据回退提示置顶。
**验收**：往复机端到端冒烟通过；报告无 orbit 图；证据链含 ≥1 条曲轴角对齐特征。

#### Story S2-4（Should · 1 SP）：sandbox 镜像更新 + PDF 验证

**范围**：在 sandbox Dockerfile 加 `weasyprint` + 中文字体（思源黑体或 Noto Sans CJK）；验证日报 + 诊断 PDF 都能正常生成。
**验收**：`write_diagnosis_report(payload, "pdf")` 不抛 ImportError；中文字符正常渲染；表格分页无截断。
**风险**：如镜像更新不在 Sprint 团队职责范围，作为外部依赖跟踪，本 Story 降级为"出 PR + 等运维合并"。

#### Story S2-5（Should · 1 SP）：真实历史故障案例库接入（探索）

**范围**：在 `query_diagnosis.py` 加 `--history-source` 参数；调研真实案例库接口（与现场对接）；如接口未就绪，则在本 Story 完成接入设计文档与 placeholder 实现。
**验收**：要么真实接入并 `historical_cases[].data_source=real_history`；要么有完整对接方案文档。

#### Story S2-6（Must · 2 SP）：单元测试与最小回归

**范围**：

- `backend/tests/test_query_diagnosis.py`：参数解析、demo_fallback、`--mode screening` 缩样、错误结构化输出。
- `backend/tests/test_diagnosis_features.py`：三类 `--rules-skill` 都产出 `rule_matches`、`verdict` 三态、缺规则文件容错、`supporting_evidence_indices` 索引正确性。
- `backend/tests/test_export_diagnosis_report.py`：Markdown 章节完整、in-process API 与 CLI 一致、PDF ImportError 行为、SVG > 50KB 落盘。
- 数据契约测试：query → features → export 最小链路。
- 三个 SOUL.md 静态扫描禁词（`SESSION INTENT` / `SUMMARY` / `ARTIFACTS` / `NEXT STEPS`）。

**验收**：pytest 全绿；契约测试覆盖 query → features → export；静态扫描脚本入 `backend/tests/`。

#### Story S2-7（Should · 0.5 SP）：双 Sprint 收尾文档

**范围**：在设计文档加 changelog + 运行手册片段（如何切到真实数据 / 如何更新规则）。

### 2.4 S2 Summary

```text
Must Stories（共 7 SP）:
1. reciprocating-fault-diagnosis skill 骨架 — 1.5 SP
2. fault-diagnosis--rotating SOUL.md — 2 SP
3. fault-diagnosis--reciprocating SOUL.md — 1.5 SP
4. 单元测试与回归 — 2 SP

Should Stories（共 2.5 SP，容量允许时推进）:
5. sandbox 镜像 + PDF 验证 — 1 SP（依赖运维）
6. 真实历史故障案例库接入 — 1 SP（依赖现场）
7. 双 Sprint 收尾文档 — 0.5 SP

不承诺:
- 跨子 agent 故障 code 自动校验脚本（CI 治理，列入 follow-up）
- 三类规则 skill 的规则评审完整覆盖（仅占位规则跑通端到端）
```

---

## 3. 不建议任一 Sprint 承诺的内容

### 跨子 agent 故障 code 自动校验脚本

**原因**：三个 skill 的 code 列表已在设计文档 §4.4 + S1-2 评审中明确对齐；自动化校验属于工程治理。
**建议**：作为 follow-up，在 `data-analyst` 注册 `fault_family_codes.json` + CI 校验脚本。

### 三类规则 skill 的现场标定 + 完整规则评审

**原因**：每个故障家族需要现场样本 + 领域专家逐条评审，工作量超出双 Sprint。
**建议**：S1 / S2 仅交付占位规则跑通端到端；规则评审独立工作流，可与现场联调并行。

### vibration skill references 重写

**原因**：现有 302 行规则已经过线上验证，重写风险高于收益。
**建议**：S1-2 仅追加 code 映射段，不动既有规则文本；如需细化，单独立项。

---

## 4. 集成冒烟 vs 单元测试分工

| Sprint | 验证手段 | 范围 |
| ---- | ---- | ---- |
| S1-8 | 集成冒烟测试套 (`backend/tests/test_fault_diagnosis_smoke.py`，15 用例) | 发现层（group + 3 子 agent + skill 装配）、SOUL 契约（callback 命名 / 两阶段分工 / in-process import / present_files 白名单 / 演示数据降级 / 禁词扫描）、端到端管线（query → features → write_report，含 PDF ImportError 路径） |
| S2-6 | 单元 + 契约测试增强（pytest） | 真实 InS 接入回归、historical_cases 真实数据回归、PDF 中文字体落地验证 |

> 自动化冒烟测试**已替代** S1-8 初版的"手动 + 截图归档"方案：CI 守护契约稳定，S2 才补真实数据 / PDF 落地后的人工验证。

---

## 5. S1 交付清单（实际产出）

> 本节由 Story S1-9 在 S1 收尾时填写。

### 5.1 新增 / 修改的 agent 资产

| 文件 | 类型 | 说明 |
| ---- | ---- | ---- |
| `agents/builtin/fault-diagnosis/config.yaml` | 修改 | 升级为 `type: group`；description / tags 重写 |
| `agents/builtin/fault-diagnosis/SOUL.md` | 修改 | 改写为 group 引导页 |
| `agents/builtin/fault-diagnosis--pump/{config.yaml,SOUL.md}` | 新建 | 完整 SOUL（389 行，三轮 GenUI + 两阶段分工 + in-process 导出） |
| `agents/builtin/fault-diagnosis--rotating/{config.yaml,SOUL.md}` | 新建 | placeholder SOUL（S2-2 落地） |
| `agents/builtin/fault-diagnosis--reciprocating/{config.yaml,SOUL.md}` | 新建 | placeholder SOUL（S2-3 落地） |

### 5.2 新增的 skill 资产

| 路径 | 说明 |
| ---- | ---- |
| `skills/custom/pump-fault-diagnosis/{SKILL.md,references/diagnosis-rules.md}` | 9 项故障家族 code mapping + 3 条占位规则（不平衡 / 汽蚀 / 流量低于最小连续流量） |
| `skills/custom/reciprocating-fault-diagnosis/{SKILL.md,references/diagnosis-rules.md}` | 11 项故障家族 code mapping + 3 条占位规则（吸气阀 / 活塞环 / 十字头敲缸）。**注**：本应由 S2-1 落地，S1 阶段提前完成以解锁 reciprocating placeholder agent 的 skill 装配。 |
| `skills/custom/vibration-fault-diagnosis/SKILL.md` | 末尾追加 12 项故障家族 code mapping（与 §4.4 旋转机组对齐） |

### 5.3 新增的脚本资产

| 路径 | 行数 | 单测 | 说明 |
| ---- | ---- | ---- | ---- |
| `skills/custom/data-analyst/scripts/query_diagnosis.py` | 425 | `tests/test_query_diagnosis.py` (19) | Stage 1 聚合趋势特征拉取 + 演示数据回退 |
| `skills/custom/data-analyst/scripts/diagnosis_features.py` | 595 | `tests/test_diagnosis_features.py` (21) | Stage 2 特征 + 规则匹配 + ECharts |
| `skills/custom/data-analyst/scripts/export_diagnosis_report.py` | 195 | 与下行共测 | 6 节 Markdown / HTML 渲染纯函数 |
| `skills/custom/data-analyst/scripts/export_report.py` | 修改 | `tests/test_export_diagnosis_report.py` (14) | `SUPPORTED_REPORT_TYPES` 加 `"diagnosis"`、`write_report` / `load_payload` / `_output_dir` 加 diagnosis 分支 |
| — | — | `tests/test_fault_diagnosis_smoke.py` (15) | 集成冒烟（覆盖 S1-8 全部 acceptance） |

**测试规模**：69 个 fault-diagnosis 专属单测 + 集成冒烟，全部 PASSED；与日报 / 周报 / 月报回归共 100+ 测全绿；ruff 无新增告警。

### 5.4 设计文档同步

- §4.4 顶部加入 S1-2 评审 changelog（机泵 8→9、往复机 10→11、旋转机 12 不变 + runout 双标）
- §5.3 改写为"扩展 SUPPORTED_REPORT_TYPES"路径（核验后取代原"提升私有 API / 复制实现"备选）
- §6.1 / §6.2 数量与 §4.4 对齐（轴承损伤合并到 family 层，subtype 报告内细化）
- §9 PDF 行 + group 升级行重写（链接到 §9.1 迁移策略）

---

## 6. 双 Sprint 完结总览

由 S2-7 在双 Sprint 收尾时确认所有 Story 交付状态：

```text
□ S1 完成（机泵端到端 MVP）：
  ✅ S1-1 group + 4 config.yaml
  ✅ S1-2 故障家族 code 评审 + vibration mapping 段
  ✅ S1-3 pump-fault-diagnosis skill 骨架（9 family + 3 占位规则）
  ✅ S1-4 query_diagnosis.py（19 单测）
  ✅ S1-5 diagnosis_features.py（21 单测）
  ✅ S1-6 export_diagnosis_report.py + export_report.py 注册 diagnosis（14 单测）
  ✅ S1-7 fault-diagnosis--pump SOUL.md（389 行完整实现）
  ✅ S1-8 集成冒烟测试套（初版 15 用例 → S2-6 扩展为 35 用例）
  ✅ S1-9 S1 文档收尾

□ S2 完成（旋转机 / 往复机扩展 + 单测增强）：
  ✅ S2-1 reciprocating-fault-diagnosis skill 骨架（11 family + 3 占位规则；提前在 S1 完成）
  ✅ S2-2 fault-diagnosis--rotating SOUL.md（407 行 / 12 项 focus codes / 保留 orbit）
  ✅ S2-3 fault-diagnosis--reciprocating SOUL.md（392 行 / 11 项 focus codes / 跳过 orbit）
  ⏸ S2-4 sandbox 镜像 weasyprint + 中文字体（依赖运维 PR；降级路径已就位）
  ⏸ S2-5 真实历史故障案例库接入（依赖现场对接；query_diagnosis 已预留 hook）
  ✅ S2-6 单测增强 + 集成冒烟覆盖三个子 agent（35 用例，含 cross-talk 矩阵 / orbit 分流 / 三方 e2e）
  ✅ S2-7 双 Sprint 收尾文档（本节 + 运行手册）

□ 仍依赖外部的项目（移交 follow-up）：
  □ sandbox 镜像更新（weasyprint + 中文字体）→ 等运维 PR 合并后 PDF 即可用
  □ 现场 InS 部署接入（往复机的曲轴角 / 缸压通道）→ 决定演示数据回退退场时机
  □ 现场历史故障案例库 API → 决定 historical_cases 真实数据接入时机
  □ 领域专家逐条评审占位规则 → 真实样本规则
  □ 跨子 agent 故障 code 自动校验脚本（CI 治理）
```

---

## 7. 运行手册（如何切到真实数据 / 如何更新规则）

### 7.1 切到真实 InS 数据

`query_diagnosis.py` 已实现"InS 优先 + 演示数据回退"双路径，sandbox 部署条件满足即自动切换：

1. **环境准备**：在 sandbox 中部署 `features-tool/` 仓库到 `FEATURES_TOOL_ROOT`（默认 `/opt/features-tool`），并部署 `ins-extract-trend-features` skill 到 `INS_SKILL_ROOT`（默认 `/mnt/skills/custom`）。
2. **环境变量**：确保 InS API 凭证（`DATA_PLATFORM_URL` / `DATA_PLATFORM_TOKEN` 等）在 sandbox 进程环境可见。
3. **验证**：触发任一子 agent 的诊断流程，最终报告顶部不再出现 `⚠️ 当前为演示数据回退` 警告即说明已切到真实路径。
4. **回退监控**：读取 `/mnt/user-data/outputs/query_diagnosis.json` 的 `data_source` 字段（`ins` / `demo_fallback`）和 `warnings[]` 列表，可定位具体哪台设备 / 哪个测点回退到了演示数据。

### 7.2 更新规则库

三个规则 skill 的 `references/diagnosis-rules.md` 是诊断结论的权威来源，更新流程：

1. **占位规则 → 真实规则**：编辑对应文件（`pump-fault-diagnosis` / `reciprocating-fault-diagnosis` / `vibration-fault-diagnosis`），按现有"### 故障家族中文名"章节格式新增或替换规则。
2. **新增故障家族**（罕见操作）：
   - 在对应 skill 的 `SKILL.md` "Fault family code mapping" 表中新增一行 `<新 code> | <章节中文名>`。
   - 在 `diagnosis-rules.md` 新增对应章节。
   - 在 SOUL.md 的 Round 2 表单 `fields` 中新增一项 `focus_<code>` checkbox。
   - 在设计文档 §4.4 `fd-{kind}-focus` 列表中加入新 code。
   - 运行 `pytest tests/test_fault_diagnosis_smoke.py::test_subagent_focus_codes_match_design`，确保静态扫描通过。
3. **`diagnosis_features.py` 关键词识别能力**：脚本通过特征别名（`pp_value` / `rms` / `1X` 等）匹配规则文本。如规则文本只用英文专业术语，可考虑：(a) 在规则中追加中文标签；(b) 在 `diagnosis_features._section_matches_evidence()` 的 `aliases` 字典中扩充别名。Sprint S2 已确认 vibration skill 的英文规则与演示数据存在天然不匹配，**等真实 InS 数据接入后再调优**。

### 7.3 PDF 启用

PDF 已通过 `export_report.py` 的 `_write_pdf` 路径接好，等 sandbox 镜像装上 `weasyprint` + 中文字体（推荐 Noto Sans CJK 或 思源黑体）后**无需改任何代码**即可使用。验证方法：在 SOUL 的 `try/except ImportError` 不再被触发，前端报告底部出现 `[下载 PDF](...)` 链接而不是 `PDF 不可用（weasyprint 未安装）`。

### 7.4 历史案例库接入

`diagnosis_features.build_historical_cases` 当前返回 `data_source=demo_fallback` 的演示数据。真实接入路径：

1. 在 `query_diagnosis.py` 加 `--history-source` 参数（已预留位置）。
2. 在 `diagnosis_features.py` 中替换 `build_historical_cases` 的实现，从真实历史案例库 API 检索同设备 / 同故障家族的历史记录。
3. 真实记录返回时 `data_source` 字段填 `real_history`；SOUL 在渲染 `card` 时会自动去掉"演示 · "前缀（步骤 5 中已按 `data_source == "demo_fallback"` 判定）。
