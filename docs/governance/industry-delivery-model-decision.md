# 行业层交付模型决策

> **版本**：v1.0（建议稿）
> **日期**：2026-05-23
> **状态**：已决策（2026-05-23）
> **依赖**：
> - [行业能力三层分类结论](./industry-capability-layer-classification.md)（ISSUE-13）
> - [三层产品结构原则](./three-layer-product-structure-principles.md)（ISSUE-14）
>
> 本文档为行业层交付模型提供完整分析和决策框架，供 Workshop 评审使用。

---

## 一、三种候选方式详细对比

### 1.1 方式 A：同仓同发（Monorepo, Unified Release）

**描述**：行业代码与 Core/Enterprise 代码在同一仓库中，所有层使用统一的版本号和发布节奏。

**仓库结构**：
```
deer-flow/
├── backend/
│   └── packages/
│       ├── harness/deerflow/          # Core + Enterprise
│       └── industry/                  # Industry Solution Layer
│           ├── power/                 # 电力行业
│           ├── petrochemical/         # 石化行业
│           └── steel/                 # 钢铁行业
├── skills/
│   ├── public/                        # 通用 Skill
│   └── industry/                      # 行业 Skill
│       ├── power/
│       ├── petrochemical/
│       └── steel/
└── frontend/
    └── src/
        └── app/
            └── workspace/
                └── industry/          # 行业前端页面
```

**优势**：
- 版本一致性：所有组件使用同一版本号，不会出现版本不匹配
- 集成测试简单：一次 PR 可跨层修改和测试
- 原子性变更：跨层变更（如 Core API 变更 + Industry 适配）在一个 commit 中完成
- 代码发现性：所有代码在同一个仓库，开发者容易找到相关代码
- CI/CD 简单：单一 CI 管道，无需跨仓库协调

**劣势**：
- 发布耦合：Industry 层必须跟随 Core 的发布节奏，即使 Industry 层没有变更
- 仓库体积：随行业增多而增大，clone 时间增加
- 权限粗粒度：难以按行业控制代码访问权限
- 行业团队依赖平台 CI：行业团队无法独立配置 CI/CD

**适用场景**：
- 团队规模小（<20 人）
- 行业数量少（1-3 个）
- 行业与平台变更频率相近
- 优先代码复用和集成效率

### 1.2 方式 B：同仓分发（Monorepo, Independent Release）

**描述**：行业代码与 Core/Enterprise 代码在同一仓库中，但行业层有独立的版本号和发布节奏。

**仓库结构**：
```
deer-flow/
├── backend/
│   └── packages/
│       ├── harness/deerflow/          # Core + Enterprise (v2.3.0)
│       └── industry/                  # Industry Solution Layer
│           ├── power/                 # @deerflow/industry-power v1.5.0
│           ├── petrochemical/         # @deerflow/industry-petro v2.1.0
│           └── steel/                 # @deerflow/industry-steel v0.9.0
├── skills/
│   ├── public/                        # 随 Core 发布
│   └── industry/                      # 随各自行业发布
└── ...
```

**发布模型**：
```
Core Platform:     v2.3.0 ─── v2.3.1 ─── v2.4.0 ───>
Power Industry:    v1.5.0 ──────────── v1.6.0 ──────>
Petrochemical:     v2.1.0 ─── v2.1.1 ─── v2.2.0 ───>
Steel Industry:    v0.9.0 ──────────────────── v1.0.0>
```

**优势**：
- 代码共享方便：跨层引用只需相对路径导入
- 发布独立：每个行业按自己的节奏发布，不被 Core 阻塞
- 仍需 Code Review：跨层修改仍需平台团队 Review
- 版本灵活：Core 升级不影响行业层的已有版本

**劣势**：
- 版本管理复杂：需要维护多套版本号，Core 与 Industry 的兼容性矩阵
- 依赖地狱：Industry v1.6.0 要求 Core >= v2.4.0，Industry v1.5.0 要求 Core >= v2.3.0
- CI/CD 复杂：需要多套发布管道，按行业/层级触发
- 原子性变更困难：跨层变更需要协调多个版本的发布

**适用场景**：
- 团队规模中等（20-50 人）
- 行业数量中等（3-8 个）
- 行业迭代节奏明显快于 Core
- 愿意投入 CI/CD 基础设施

### 1.3 方式 C：独立方案层管理（Separate Repos）

**描述**：每个行业（或行业组）有独立的 Git 仓库，通过包依赖（pip/npm）引用 Core SDK。

**仓库结构**：
```
deer-flow-core/                         # Core + Enterprise (独立仓库)
├── backend/packages/harness/deerflow/
├── skills/public/
└── frontend/

deer-flow-industry-power/               # 电力行业 (独立仓库)
├── skills/industry/power/
├── backend/industry/power/
└── depends: deer-flow-core >= 2.3.0

deer-flow-industry-petrochemical/       # 石化行业 (独立仓库)
├── skills/industry/petrochemical/
├── backend/industry/petrochemical/
└── depends: deer-flow-core >= 2.3.0
```

**优势**：
- 完全解耦：行业团队完全自治，可独立选择技术栈和工具链
- 独立迭代：行业层发布不受任何人阻塞
- 权限隔离：按仓库控制访问权限，行业代码对平台团队不可见（如需）
- CI/CD 独立：每个行业配置最适合自己的 CI/CD

**劣势**：
- 代码复用困难：跨仓库共享代码需要发布 SDK 包
- Core API 变更影响大：升级 Core SDK 版本需要每个行业仓库分别适配
- 维护成本高：每个仓库独立维护依赖、安全补丁、CI/CD 配置
- 集成测试困难：跨仓库的集成测试需要额外的编排
- 版本碎片化：不同行业可能运行不同版本的 Core，增加支持复杂度

**适用场景**：
- 团队规模大（50+ 人）
- 行业数量多（8+ 个）
- 行业由独立团队/公司开发
- 行业与平台技术栈不同
- 需要严格的代码访问控制

### 1.4 对比矩阵

| 维度 | 同仓同发 (A) | 同仓分发 (B) | 独立方案层 (C) |
|------|:--:|:--:|:--:|
| **行业迭代独立性** | 低 | 中 | 高 |
| **代码复用便利性** | 高 | 高 | 低 |
| **CI/CD 复杂度** | 低 | 中 | 高 |
| **版本管理复杂度** | 低 | 中 | 高 |
| **跨层变更原子性** | 高 | 中 | 低 |
| **权限隔离** | 低 | 中 | 高 |
| **仓库体积增长** | 高 | 高 | 低（每个） |
| **集成测试便利性** | 高 | 中 | 低 |
| **维护成本** | 低 | 中 | 高 |
| **团队自治程度** | 低 | 中 | 高 |

---

## 二、推荐决策

### 2.1 推荐方案：方式 B（同仓分发）

**推荐理由**：

1. **行业迭代独立性**（第一优先级）：当前行业需求变化快（每周/每日级），不能被 Core 的两周发布节奏阻塞。方式 B 允许行业按需发布。

2. **代码复用便利性**（第二优先级）：当前行业数量为电力（含旋转/往复/振动/泵）、石化（含腐蚀），预计后续扩展到钢铁。3-5 个行业在同仓库内共享代码比跨仓库更高效。

3. **CI/CD 复杂度**（第三优先级）：虽然方式 B 需要更复杂的 CI/CD，但投入是可控的。Nuxt、Vercel 等成熟工具对 monorepo 独立发布有原生支持。

4. **过渡成本最低**：当前代码已在 monorepo 中，选择方式 B 只需增加行业层的独立版本号，无需大规模仓库迁移。

### 2.2 决策标准评估

| 标准 | 权重 | 方式 A 得分 | 方式 B 得分 | 方式 C 得分 |
|------|------|:--:|:--:|:--:|
| 行业迭代独立性 | ★★★ | 1 | 3 | 5 |
| 代码复用便利性 | ★★ | 5 | 4 | 1 |
| CI/CD 复杂度 | ★ | 5 | 3 | 1 |
| **加权总分** | | **2.3** | **3.2** | **2.7** |

（5=最优，1=最差）

### 2.3 决策记录

| 字段 | 内容 |
|------|------|
| **决策** | 同仓分发（Monorepo, Independent Release） |
| **备选方案** | 同仓同发（Monorepo, Unified Release） |
| **决策日期** | 2026-05-23 |
| **决策参与者** | 杨海（行业解决方案负责人 + 技术负责人） |
| **生效日期** | 2026-09-01 |
| **复审日期** | 2027-03-01（6 个月后评估是否需要迁移到方式 C） |

---

## 三、影响评估

### 3.1 对现有仓库结构的影响

**当前结构 → 目标结构**：

```
当前（方式 A 风格）：              目标（方式 B 风格）：
deer-flow/                         deer-flow/
├── backend/                       ├── backend/
│   └── packages/                  │   └── packages/
│       └── harness/               │       ├── harness/deerflow/    → v2.x
│           └── deerflow/   ← 行业代码混在这里                     │       └── industry/
│                                  │           ├── power/          → @deerflow/industry-power v1.x
                                   │           ├── petrochemical/  → @deerflow/industry-petro v2.x
                                   │           └── steel/          → @deerflow/industry-steel v0.x
                                   ├── skills/
                                   │   ├── public/                 → 随 Core 发布
                                   │   └── industry/               → 随各自行业发布
                                   │       ├── power/
                                   │       ├── petrochemical/
                                   │       └── steel/
                                   └── frontend/
                                       └── src/app/workspace/
                                           └── industry/           → 行业前端页面
```

**变更内容**：
1. 新建 `backend/packages/industry/` 目录，按行业分子目录
2. `skills/custom/` 下的 `ins-*` 和诊断 Skill 迁移到 `skills/industry/{industry}/`
3. `skills/custom/daily-report` 保留在 custom（通用）
4. 前端新增 `workspace/industry/` 路由组
5. 行业包各自的 `pyproject.toml` / `package.json`，声明独立的版本号和对 Core 的依赖版本范围

**不需变更**：
- `backend/packages/harness/deerflow/` 核心模块不变
- `backend/app/gateway/` API 路由不变（行业 RPC 路由可随 Core 发布）
- 前端 Core 组件不变

### 3.2 对 CI/CD 和版本管理的影响

**版本管理**：
```
Core Platform:       语义版本 (MAJOR.MINOR.PATCH)
Enterprise Control:  随 Core 版本（同一发布单元）
Industry Power:      独立语义版本，依赖 Core >= MIN_VERSION
Industry Petro:      独立语义版本，依赖 Core >= MIN_VERSION
Industry Steel:      独立语义版本，依赖 Core >= MIN_VERSION
```

**CI/CD 管道**：
```
PR → 变更检测 → 触发对应管道
  ├─ Core/Enterprise 变更  → Core CI → Core 发布
  ├─ Industry Power 变更   → Power CI → Power 发布
  ├─ Industry Petro 变更   → Petro CI → Petro 发布
  ├─ Industry Steel 变更   → Steel CI → Steel 发布
  └─ 跨层变更             → Core CI → 相关 Industry CI → 顺序发布
```

**兼容性矩阵**（自动测试）：
```
CI 管道中维护兼容性测试矩阵：
  - Core v2.3.x ← Industry Power v1.x （当前组合）
  - Core v2.3.x ← Industry Power v1.(x-1) （上一版本）
  - Core v2.4.x ← Industry Power v1.x （向前兼容）
```

### 3.3 对 2026-09 之后排期方式的指导

**排期模型**：

```
Core Platform:      2 周迭代（Sprint）
  ├─ Sprint N:   开发 + Code Review
  ├─ Sprint N+1: 测试 + 灰度发布
  └─ 全量发布在 Sprint 结束时

Industry Layer:     按需迭代（Continuous）
  ├─ Hotfix:     同一天（行业紧急修复）
  ├─ Feature:    1-2 周（新诊断 Skill / 报告模板）
  └─ 发布无需对齐 Core Sprint
```

**排期规则**：
1. Core 发布的 **前 1 周**为"冻结期"，行业层大型变更应在此之前完成
2. 行业层可在 Core 冻结期内发布 hotfix，但不建议发布大型 feature
3. 跨层变更需在 Core Sprint Planning 中提前协调
4. 每季度一次跨层对齐会议，评估兼容性矩阵和依赖版本

**Q3 2026 建议排期**：
```
Jul 2026:  完成仓库结构调整（目录迁移、版本号初始化）
Aug 2026:  CI/CD 管道改造完成，行业包独立发布就绪
Sep 2026:  方式 B 正式运行，行业层开始独立发版
```

---

## 四、协作规则

### 4.1 跨团队协作方式

**组织模型**：

```
                    ┌─────────────────────┐
                    │   架构负责人（最终决策） │
                    └─────────┬───────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
  ┌───────┴───────┐   ┌───────┴───────┐   ┌───────┴───────┐
  │  平台团队      │   │  电力行业团队  │   │  石化行业团队  │
  │  (Core + Ent) │   │  (Power)      │   │  (Petro)      │
  └───────────────┘   └───────────────┘   └───────────────┘
```

**协作规则**：

| 场景 | 谁负责 | 谁需要知晓 | 谁审批 |
|------|--------|-----------|--------|
| Core API 新增 | 平台团队 | 所有行业团队 | 架构负责人 |
| Core API 废弃 | 平台团队 | 所有行业团队（提前 1 个版本通知） | 架构负责人 |
| Core Bug Fix | 平台团队 | 无需通知（向后兼容） | 平台 Tech Lead |
| Industry Skill 新增 | 行业团队 | 平台团队（注册到 Skill 目录） | 行业负责人 |
| Industry Skill 修改 | 行业团队 | 无需通知 | 行业负责人 |
| Industry 依赖 Core 升级 | 行业团队 | 平台团队（兼容性验证） | 行业负责人 + 平台 Tech Lead |
| 跨层 Breaking Change | 提出方 | 所有受影响方 | 架构负责人 |

### 4.2 变更影响范围通知机制

**通知渠道**：
- **Core 变更影响行业**：在 Core Release Notes 中标注 `[Industry Impact]` 标签，通过 Slack `#deer-flow-releases` 频道通知
- **行业变更影响 Core**：通过 GitHub Issue 标记 `core-dependency` 标签，@平台团队
- **跨行业影响**：通过 `#deer-flow-industry` 频道通知所有行业团队

**通知时效**：
| 变更类型 | 提前通知时间 | 通知方式 |
|----------|------------|----------|
| Core API 新增 | 与发布同步 | Release Notes |
| Core API 废弃 | 至少 1 个版本（2 周）提前 | Release Notes + Slack @channel |
| Core Breaking Change | 至少 2 个版本（4 周）提前 | Release Notes + Slack + GitHub Discussion |
| Industry 紧急 Hotfix | 发布后即时通知 | Slack |
| 跨层协调变更 | Sprint Planning 对齐 | GitHub Issue + Slack |

### 4.3 责任边界

| 责任项 | 平台团队 | 行业团队 |
|--------|:--:|:--:|
| Core DSL 引擎维护 | ✓ | |
| Core Agent 框架维护 | ✓ | |
| Core RAG/知识库维护 | ✓ | |
| Core 安全补丁 | ✓ | |
| 行业 Skill 开发和维护 | | ✓ |
| 行业报告模板开发 | | ✓ |
| 行业 RPC 适配器维护 | | ✓（平台团队提供 RPC 框架） |
| Core API 向后兼容 | ✓ | |
| Industry 与 Core 兼容性测试 | ✓（提供测试框架） | ✓（编写测试） |
| 租户级问题排查 | ✓（Core 层面） | ✓（Industry 层面） |
| CI/CD 基础设施 | ✓ | |

---

## 五、过渡期安排

### 5.1 时间线

```
Phase 1: 准备期（2026-06）
  ├─ 6/01-6/15: Workshop 评审本文档，做出正式决策
  ├─ 6/16-6/30: 目录结构调整方案设计
  └─ 交付物: 迁移计划文档

Phase 2: 迁移期（2026-07）
  ├─ 7/01-7/15: 目录迁移（skills/custom/ins-* → skills/industry/{industry}/）
  ├─ 7/16-7/31: 版本号初始化（各行业包建立独立的 pyproject.toml）
  └─ 交付物: 迁移完成的代码

Phase 3: 基础设施期（2026-08）
  ├─ 8/01-8/15: CI/CD 管道改造（变更检测 + 行业独立发布）
  ├─ 8/16-8/31: 兼容性测试矩阵搭建 + 试运行
  └─ 交付物: 就绪的 CI/CD + 兼容性测试报告

Phase 4: 正式运行（2026-09-01）
  ├─ 方式 B 正式启用
  ├─ 行业层开始独立发版
  └─ 2 周后回顾检查
```

### 5.2 过渡期规则

1. **冻结期**：Phase 2 迁移期间（7/01-7/15），暂停行业层的新功能开发（hotfix 除外）
2. **双轨期**：Phase 3 试运行期间（8/16-8/31），新旧发布管道并行，旧管道为主
3. **回退策略**：如 Phase 4 出现严重问题，可回退到统一发布模式（方式 A），回退窗口为 9/01-9/15
4. **风险缓解**：迁移前对 `skills/custom/` 做完整备份，每个行业 Skill 有独立的 Git 历史

---

## 六、修订记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| v1.0 | 2026-05-23 | 初始建议稿，待 Workshop 评审 | 架构分析（自动化） |
