# A股投研技能迁移改造计划（backend2/custom → claude-skills）

## 1. 目标与约束

- 目标：基于 `/home/dingkd/deer-flow-backup/backend2/skills/custom` 的现有能力，改造 `/home/dingkd/deer-flow-backup/claude-skills` 的 skills，使其面向 **A股买方投研** 场景，统一中文表述与中文输出，并将数据/API依赖切换到 Tushare 等 A 股数据源。
- 约束1：保留 `claude-skills` 的目录骨架（顶层产品线与 skills 分层不重构）。
- 约束2：删除不适合 A 股投资研究的 skills。
- 约束3：对保留/新增 skills 的 `SKILL.md` 与配套 `references/*.md` 做中文化与 A 股化改造，确保调用链路与口径一致。
- 约束4：交付中补充 `README.md` 与 `ROADMAP.md`，用于说明技能体系、使用方式与后续演进路线。

## 2. 当前清单与差异基线

### 2.1 源目录（backend2/custom）已存在 skills

- 3-statements
- catalyst-calendar
- check-deck
- check-model
- comps-analysis
- competitive-analysis
- dcf-model
- earnings-analysis
- earnings-preview
- finance-pdf-ingest
- idea-generation
- initiating-coverage
- model-update
- morning-note
- ppt-template-creator
- profit-forecast
- sector-overview
- stock-deep-research
- stock-mapper
- stock-news-get
- thesis-tracker
- xueqiu-hotposts-analyzer

### 2.2 目标目录（claude-skills）当前 skills

- `financial-analysis/skills`：
  - 3-statements
  - check-deck
  - check-model
  - comps-analysis
  - competitive-analysis
  - dcf-model
  - lbo-model
  - ppt-template-creator
  - skill-creator
- `equity-research/skills`：
  - catalyst-calendar
  - earnings-analysis
  - earnings-preview
  - idea-generation
  - initiating-coverage
  - model-update
  - morning-note
  - sector-overview
  - thesis-tracker

### 2.3 差异判断（用于实施）

- 同名可直接对齐改造：17 个（两侧重叠技能）。
- 仅在 `claude-skills`：`lbo-model`、`skill-creator`。
- 仅在 `backend2/custom`：`finance-pdf-ingest`、`profit-forecast`、`stock-deep-research`、`stock-mapper`、`stock-news-get`、`xueqiu-hotposts-analyzer`（候选新增到 `claude-skills` 现有产品线下）。

## 3. 技能去留与放置策略

### 3.1 删除清单（不适合 A 股买方投研）

- 删除 `financial-analysis/skills/lbo-model`

### 3.2 `skill-creator` 复核结论

- 结论：`skill-creator` **可用于 A 股买方投研的“技能工程化”场景**，用于持续构建/迭代投研技能，不直接产出研究结论。
- 处理策略：保留 `financial-analysis/skills/skill-creator`，并改为中文描述，补充买方投研专用示例（如：因子研究技能、组合归因技能、公告事件抽取技能）。
- 触发边界：仅在“创建/改造技能”请求触发，不在日常公司研究、估值建模、晨会纪要任务中触发。

### 3.3 保留并改造清单（同名覆盖）

- 对重叠 skills 执行“结构不变、内容替换”：以 `backend2/custom/<skill>` 为基线，覆盖 `claude-skills` 同名 skill 的 `SKILL.md` 与 `references` 文档内容。
- 覆盖范围包含：
  - front matter（name/description）
  - 使用场景、任务流程、质量标准
  - 引用规范与交付规范
  - 依赖 API/MCP 定义

### 3.4 新增清单（保持目录骨架不变前提下）

- 新增到 `equity-research/skills`：
  - stock-deep-research
  - stock-mapper
  - stock-news-get
  - xueqiu-hotposts-analyzer
  - profit-forecast
  - finance-pdf-ingest
- 新增目录结构遵循现有规则：每个 skill 至少包含 `SKILL.md`，若源 skill 含 `references` 则完整拷贝。

## 4. A股化改造规则（逐 skill 执行）

### 4.1 语言与输出

- 文档与提示词全部中文化：标题、说明、流程、检查项、交付物统一中文。
- 输出要求明确写入“中文输出”，并指定模板风格为 **A股买方投研语境**（组合决策、风险收益、仓位与催化跟踪）。

### 4.2 数据源与 API 依赖替换

- 将美股/海外数据源描述替换为 A 股数据体系：
  - 优先：Tushare（行情、财务、估值、交易日历）
  - 可并行：交易所公告、巨潮资讯、东方财富、雪球等中文信源
- 在每个 skill 中显式写明：
  - 必需数据接口
  - 字段口径（TTM、同比/环比、复权口径）
  - 时间有效性要求（如 T+1 更新）

### 4.3 买方交付规范与质量

- 每个报告类 skill 必须包含：
  - 风险提示章节
  - 数据来源与时间戳
  - 不得编造数据约束
  - 组合相关字段（持仓逻辑、触发条件、失效条件）中的至少一项

### 4.4 文档补充（README 与 ROADMAP）

- 在 `claude-skills` 根目录新增/更新 `README.md`：
  - 技能目录总览（financial-analysis / equity-research）
  - 买方投研使用路径（选股→深研→估值→跟踪→复盘）
  - 关键数据源说明（Tushare、交易所公告、雪球等）
  - 触发示例与输出样例约定（中文）
- 在 `claude-skills` 根目录新增/更新 `ROADMAP.md`：
  - 近期（P0）：完成中文化、A股API替换、关键技能补齐
  - 中期（P1）：加入组合归因/风险暴露/事件驱动模块化技能
  - 远期（P2）：形成多策略（成长/价值/红利/量化）技能分层与评测机制

## 5. 执行步骤（实施时按序）

1. 建立文件映射表：输出“同名覆盖 / 新增 / 删除”三类路径清单。
2. 执行删除：移除 `lbo-model` 目录。
3. 改造 `skill-creator`：中文化并加入买方技能工程示例与触发边界。
4. 执行同名覆盖：逐个 skill 覆盖 `SKILL.md` 与 `references`。
5. 执行新增迁入：将 6 个缺失的 A 股技能迁入 `equity-research/skills`。
6. 统一检查 front matter：`name` 与目录名一致，`description` 为中文且明确 A 股场景。
7. 全量检索校验：排查英文默认输出、SEC/EDGAR/美股 API 残留，替换为 A 股数据源表述。
8. 生成并完善 `README.md` 与 `ROADMAP.md`，确保与实际技能清单一致。
9. 结构校验：确认 `claude-skills` 顶层目录结构未被改动，仅发生 skills 内容层变更。

## 6. 验收标准

- 目录骨架保持不变（仅 skills 子目录增删改，顶层结构不重排）。
- 删除项（`lbo-model`）已移除，且不再被技能索引引用。
- `skill-creator` 已完成买方场景化改造，并具备明确触发边界。
- 所有保留/新增 skills 文档为中文，输出要求为中文。
- 所有关键技能依赖已切换至 Tushare 等 A 股 API 表述，无美股专用依赖残留。
- 随机抽查至少 5 个 skill：`SKILL.md` 与 `references` 的语言、流程、数据源、合规项一致。
- `README.md` 与 `ROADMAP.md` 存在且内容与当前技能清单一致。

## 7. 风险与回滚

- 风险：覆盖过程中遗漏 `references` 子文件，导致技能说明与主文档不一致。
- 风险：同名 skill 结构差异导致链接失效（相对路径引用）。
- 回滚：先记录变更前文件清单；若校验失败，按清单回退对应 skill 目录并重新覆盖。
