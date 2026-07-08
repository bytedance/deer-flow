# Release Note - Echart Skill

## v2.0.0 (2026-06-13) — Agent BI: From Chart Generator to AI Analysis Assistant

### 🧠 7 New Intelligent Engines (~4,600 LOC, 206 tests)

| Engine | Module | Description |
|--------|--------|-------------|
| **Insight Engine** | `scripts/insight_engine.py` | Auto-discovers 7 pattern types (trends, anomalies, rankings, composition, correlation, seasonality, changes) |
| **Report Engine** | `scripts/report_engine.py` | One-click professional analysis reports (Markdown/HTML/JSON) with 3 templates |
| **Semantic Layer** | `scripts/semantic_model.py` | Business-aware data modeling — natural language to SQL, column auto-classification |
| **Context Manager** | `scripts/context_manager.py` | Conversational session state, 10+ time-reference resolution ("上个月"), intent detection |
| **Forecast Engine** | `scripts/forecast_engine.py` | 4 time-series methods (MA/Exponential/Linear/Ensemble), zero external ML dependencies |
| **Attribution Engine** | `scripts/attribution_engine.py` | Root cause analysis — contribution decomposition, automatic drill-down recommendations |
| **Dashboard Insights** | `scripts/dashboard_insights.py` | Insight cards embedded in dashboards with severity grading and click-to-drill |

### 🔒 Enterprise Privacy Guard

- **Auto PII Detection**: 12 sensitive column patterns (phone, email, ID card, bank card, salary, etc.) in Chinese & English
- **Column-Level Masking**: `138****1234` / `u***@domain.com` / `3201**********1234` / `[REDACTED]`
- **Read-Only Enforcement**: Blocks DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE
- **Audit Trail**: `logs/audit.log` — JSON-lines format with timestamps, table names, query hashes
- **4-Tier Classification**: `public < internal < sensitive < restricted`

### 💻 4 New Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `/forecast` | `/f` `/预测` | Time-series forecasting with 4 methods + confidence intervals |
| `/why` | `/w` `/归因` | Root cause attribution — "why did this metric change?" |
| `/context` | `/ctx` `/会话` | Session management (start/resolve/history/list) |
| `--insights` | — | Dashboard flag to embed insight cards |

### 📊 Test Coverage

- **206 tests** (73 → 206), all passing
- New test files: `test_report_engine.py` (28), `test_semantic_model.py` (60), `test_e2e_integration.py` (26), `test_dashboard_insights.py` (19), `test_privacy_guard.py` (54)

---

## v1.4.0 (2026-06-05) - Self-Contained HTML & Configurable Architecture

### 🧩 自包含单文件 HTML（重大变更）

- **内联 ECharts 库**：图表 HTML 不再引用远程或本地 URL 的 `echarts.min.js`，而是将完整的 ECharts 库（~1.1MB）直接嵌入 HTML 中
- **内联地图脚本**：`china.js`、`world.js` 及所有省份地图 JS 均内联嵌入
- **离线可用**：生成的 HTML 为完全自包含的单文件，无外部依赖，可在任意浏览器直接打开
- **端口无关**：图表不再依赖服务器端口，服务重启换端口后旧图表仍可正常查看

### ⚙️ 灵活的服务与输出配置

- **服务默认为关闭**：`server.enabled` 默认为 `false`，生成图表后直接显示文件绝对路径
- **可配置输出目录**：`output.dir` 配置项支持自定义图表输出路径
- **集中配置文件**：新增 `echart_config.txt`，统一管理服务、输出、百度地图 AK 等配置
- **配置管理器**：新增 `scripts/config_manager.py`，自动创建默认配置、热加载

### 🗺️ 智能地图名称标准化

- **自动名称规范化**：数据中的「北京市」「广东省」「新疆维吾尔自治区」等全称自动规范化为地图所需的「北京」「广东」「新疆」
- **19 种映射规则**：覆盖所有省级行政区全称→简称的映射
- **DataFrame 级处理**：在数据层面进行标准化，保证 dataset、series.data、rawData 全部一致
- **Prompt 更新**：地图模板提示词强调使用规范简称

### 🪟 Windows 平台优化

- **静默后台服务**：使用 `CREATE_NO_WINDOW` 标志，Windows 服务进程不再弹出命令行窗口
- **端口复用**：启动服务时扫描并清理所有残留的数据服务进程，确保端口不漂移
- **进程清理增强**：PID 文件失效时仍能通过端口探测找到并终止旧进程

### 📝 文档更新

- **SKILL.md Scenario 4**：更新图表生成后处理逻辑，区分服务开启/关闭状态的输出格式
- **README**：新增自包含 HTML、配置系统、地图标准化、Windows 优化等特性说明
- **echart_config.example.txt**：配置模板文件

---

## v1.3.2 (2026-05-09) - Comprehensive Security & Robustness

### 🔒 安全审计结果

经过 5 轮深度代码审查，修复了 **10 CRITICAL + 18 HIGH + 16 MEDIUM** 级别问题。

#### SQL 注入修复
- **filter 参数** (`simple_dashboard.py`)：添加正则白名单验证，阻断分号、注释 (`--`, `/*`) 注入
- **table_name 参数** (`data_importer.py`)：CLI 传入的表名需经 `validate_table_name()` 验证
- **标识符验证** (`simple_dashboard.py`)：所有 SQL 标识符经 `_validate_identifier()` + `_quote_id()` 双重保护

#### XSS 跨站脚本修复
- ~~chart_generator.py~~（已废弃，由 Agent 直接生成替代）: 图表 title HTML 转义 (`html.escape()`)
- ~~dashboard_generator.py~~（已废弃，由 Agent 直接生成替代）: 所有用户输入 title/id 经 `html.escape()` + `json.dumps()` 安全输出
- **html_exporter.py**: title 转义 + JSON `</script>` 序列防护
- **dashboard.js**: `showToast()` 改用 `textContent` 替代 `innerHTML`

#### 服务稳定性修复
- **STATUS_DIR 崩溃** (`server_cli.py`)：修复未定义变量导致 `NameError`
- **并发竞态** (`server_cli.py`)：`fcntl.flock` 文件锁防止重复启动
- **死链接返回** (`server.py`)：`ensure_server_running()` 超时返回 None
- **连接池耗尽** (`database.py`)：空池自动创建新连接
- **线程安全** (`database.py`)：`get_repository()` 单例双重检查锁

#### Dashboard 交互修复
- **图表泄漏** (`dashboard.js`)：`applyTheme()` 主题切换后正确更新 `this.charts`
- **PDF 导出** (`dashboard.js`)：修复 `jsPDF` UMD 模块检测
- **事件监听** (`dashboard.js`)：`destroy()` 完整清理事件监听器
- **并发刷新** (`dashboard.js`)：`_refreshing` 标志防止重复刷新
- **空指针保护** (`dashboard.js`)：`filterCharts`/`sortCharts` 空元素保护
- **打印样式** (`dashboard.css`)：修复 `clip` 重置和暗色模式

#### 语法错误修复
- **simple_dashboard.py**：删除类体级别遗留的 `return name`（SyntaxError）
- **dashboard.js**：删除重复的 `init()` 方法
- **server_cli.py**：修复 `start_server()` 缩进错误的 try/except

---

## v1.3.1 (2026-05-07) - Bug Fix Release

### 🔒 安全修复

- **SQL 注入修复** (`simple_dashboard.py`)：`filter` 参数添加正则白名单验证，防止恶意 SQL 注入
- **XSS 修复** (`chart_generator.py`)：图表标题 HTML 转义，防止跨站脚本攻击
- **XSS 修复** (`dashboard_generator.py`)：所有用户提供的标题/ID 使用 `html.escape()` 和 `json.dumps()` 安全输出
- **DOM XSS 修复** (`dashboard.js`)：`showToast()` 改用 `textContent` 替代 `innerHTML`

### 🐛 致命 Bug 修复

- **服务启动崩溃** (`server_cli.py`)：修复 `STATUS_DIR` 未定义导致 `NameError` 崩溃
- **并发竞态** (`server_cli.py`)：添加 `fcntl.flock` 文件锁防止并发创建僵尸进程
- **组件泄漏** (`dashboard.js`)：修复 `applyTheme()` 主题切换后图表实例泄漏，导致所有操作崩溃
- **PDF 导出失效** (`dashboard.js`)：修复 `jsPDF` 全局检测，兼容 UMD 模块导出
- **死链接返回** (`server.py`)：修复 `ensure_server_running()` 超时仍返回假 URL
- **图表崩溃** (`simple_dashboard.py`)：修复空图表列表导致 `generate()` 崩溃
- **方法不存在** (`simple_dashboard.py`)：修复 `_detect_table()` 调用不存在的 API
- **孤儿进程泄漏** (`server.py`)：扩展清理端口范围 8100→8200

### 🛡️ 健壮性提升

- **事件监听清理** (`dashboard.js`)：`destroy()` 方法正确移除所有事件监听器
- **空指针保护** (`dashboard.js`)：`filterCharts`/`sortCharts` 添加缺失标题元素的空值保护
- **并发请求保护** (`dashboard.js`)：自动刷新添加 `_refreshing` 标志防止重复调用
- **打印样式** (`dashboard.css`)：修复打印模式隐藏元素和 `clip` 重置
- **暗色模式** (`dashboard.css`)：添加表单控件暗色主题样式
- **标识符验证** (`simple_dashboard.py`)：修复纯下划线标识符被错误拒绝
- **文件锁** (`server_cli.py`)：`start_server()` 与 `stop_server()` 互斥执行

---

## v1.3.0 (2026-05-07)

### 🎨 Dashboard 自然语言生成（重大更新）

#### 简化 Dashboard 生成
- **自然语言输入**：新增 `scripts/simple_dashboard.py`，支持用自然语言描述 Dashboard，无需编写复杂 JSON 配置
- **智能解析**：自动解析图表类型和需求，如"各地区销售柱状图"自动识别为 bar 类型
- **自动 SQL 生成**：系统根据 `group_by` 参数自动生成聚合 SQL 查询
- **智能布局算法**：自动计算最优网格列数，智能分配图表位置，地图自动 2x1 大尺寸，饼图可纵向扩展

#### 三种生成方式
```bash
# 方式一：自然语言（最简单）
/dashboard 创建销售分析仪表盘，包含：地区柱状图、品类饼图、趋势折线图、全国地图

# 方式二：简化 API
dashboard.add_chart("bar", "地区销售", group_by="region")
dashboard.add_chart("pie", "品类占比", group_by="category")

# 方式三：一行代码
create_dashboard_from_text("创建仪表盘，包含地区柱状图和品类饼图")
```

#### 支持 9 种图表类型
- **柱状图** (bar): `group_by` 参数
- **折线图** (line): `time_column` 参数
- **饼图** (pie): `group_by` 参数
- **地图** (map): `geo_column` 参数（自动识别层级）
- **散点图** (scatter): `x_column`, `y_column`
- **雷达图** (radar): `dimensions`
- **漏斗图** (funnel): `group_by`
- **树图** (treemap): `group_by`
- **旭日图** (sunburst): `hierarchy`

#### 可选参数
- `agg_column`: 聚合列（默认求和）
- `top_n`: Top N 结果
- `sort`: 排序方向（asc/desc）
- `filter`: WHERE 筛选条件

### 🎯 Dashboard 专业 UI/UX 模板

#### 现代化设计
- **卡片式布局**：700+ 行专业 CSS 模板，带阴影效果和悬停动画
- **深色/浅色主题**：完整的深色主题支持，CSS 变量驱动，一键切换
- **响应式设计**：自动适配手机（单列）、平板（2列）、桌面（3列）
- **Toast 通知**：操作反馈、错误提示、自动消失
- **加载状态**：智能加载骨架屏动画

#### 9 大交互功能
- 🌓 **主题切换**：深色/浅色主题，偏好保存到 localStorage
- 🔄 **自动刷新**：可配置刷新间隔（默认 30 秒）
- 📄 **导出 PDF**：一键导出整个仪表盘为 PDF 文件
- 🔍 **图表搜索**：按标题快速过滤图表
- ⬇️ **单独下载**：每个图表支持下载为 PNG 图片
- 🍞 **Toast 通知**：操作成功、错误提示
- ⏳ **加载状态**：智能加载骨架屏
- 📱 **响应式 Resize**：窗口改变自动调整图表大小
- 🎨 **动画效果**：卡片悬停上移、阴影增强

#### DashboardController 交互脚本
- 主题切换 + localStorage 持久化
- 自动刷新管理（可配置间隔）
- 导出 PDF（支持 html2canvas + jsPDF）
- 图表搜索/过滤功能
- 单独下载图表 PNG
- Toast 通知系统
- 响应式 resize 处理

### 🗺️ 地图三层级架构优化

#### 明确的层级划分
- **层级一：省份级别** → 使用 `china.js`（包含全国所有省份）
- **层级二：城市级别** → 使用省份 JS（如 `guangdong.js` 包含 21 城市）
- **层级三：区县街道** → 使用百度地图 API（需要 `BAIDU_AK`）

#### 使用规则
```
省份数据（北京、上海、广东） → "map": "china"
城市数据（广州、深圳、东莞） → "map": "guangdong"
区县数据（天河区、南山区） → "bmap": {...}
```

#### 本地静态地图覆盖
- ✅ **34 个省份地图**：每个省份包含所有城市数据
- ✅ **完整城市名称**：使用全称（如"广州市"、"深圳市"）
- ✅ **优先本地资源**：前两层使用本地静态地图，仅第三层需要百度 AK
- ✅ **自动降级**：精细维度自动启用百度地图 API

#### 测试验证
- 新增 `tests/test_map_charts.py` 测试套件
- 4 个测试全部通过：中国地图、世界地图、省份地图、百度地图模式
- 验证本地静态地图 JS 正确注入
- 验证不使用 $.get() 或 registerMap()

#### 文档完善
- `docs/map_chart_best_practices.md`：地图使用最佳实践
- `references/prompts/map/china_static_map.md`：中国地图模板
- `references/prompts/map/world_static_map.md`：世界地图模板
- SKILL.md Scenario 4：地图生成规则和三层级说明

### 📝 文档大幅更新

#### README 重构
- **快速开始**：环境要求、安装步骤、平台适配
- **7 个详细案例**：数据导入、SQL查询、图表生成、Dashboard、导出、数据库、轮询
- **三层级地图**：完整的使用规则和示例
- **Dashboard 三种方式**：自然语言、简化API、一行代码
- **FAQ 扩展**：新增 Dashboard 和地图问答

#### SKILL.md 更新
- Scenario 15：Dashboard 生成（4 种方法）
- 新增 `/dashboard` 指令完整说明
- 地图三层级架构决策树
- 自然语言 Dashboard 示例

### 🔧 服务管理优化

- 新增 `/start`、`/stop`、`/status` 指令
- `scripts/server_cli.py`：服务启动/停止/状态查询
- `scripts/server_status.py`：图表链接列表显示
- 自动启动服务：生成图表后自动启动本地服务器
- PID 文件追踪：防止重复启动，端口冲突处理

### 📦 功能模块

| 新增模块 | 文件 | 说明 |
|---------|------|------|
| 简化 Dashboard | `scripts/simple_dashboard.py` | 自然语言生成、自动布局 |
| Dashboard UI | `assets/dashboard/dashboard.css` | 700+ 行专业 UI 模板 |
| Dashboard 交互 | `assets/dashboard/dashboard.js` | DashboardController 类 |
| 服务管理 | `scripts/server_cli.py` | /start, /stop, /status |
| 状态查询 | `scripts/server_status.py` | 图表链接列表 |
| 地图测试 | `tests/test_map_charts.py` | 4 个地图测试 |
| 地图文档 | `docs/map_chart_best_practices.md` | 最佳实践指南 |
| 示例配置 | `examples/dashboard_config.txt` | Dashboard 示例 |

### 🎯 解决的问题

1. **Dashboard 配置复杂** → 自然语言输入，一键生成
2. **地图无法显示** → 明确三层级架构，优先本地静态地图
3. **手动启动服务** → 自动启动，返回完整 URL
4. **重复启动服务** → PID 追踪，端口冲突检测
5. **文档不够详细** → 7 个案例，完整操作指南

---

## v1.0.0 (2026-04-04)

### 🚀 新功能 (New Features)

#### 数据仪表盘 (Dashboard)
- **多图表组合布局**：新增 `scripts/dashboard_generator.py`，支持通过 `.txt` 配置文件一键生成包含多个图表的交互式仪表盘
- **CSS Grid 布局**：支持灵活的网格布局配置，可指定每个图表的行列位置和跨度
- **配置校验**：使用 pydantic 进行配置验证，自动检测图表位置重叠冲突
- **单 HTML 输出**：所有图表渲染在单个 HTML 文件中，支持任意浏览器打开

#### URL/API 数据源
- **HTTP 数据导入**：新增 URL 数据源导入能力，支持从 HTTP/HTTPS 端点导入 JSON/CSV 数据
- **认证支持**：支持 Basic Auth 和 Bearer Token 认证，使用 SecretStr 保护敏感凭证
- **JSON Schema 推断**：自动推断 JSON 响应的结构，支持嵌套对象展平（如 `user.name` → `user_name`）
- **数据刷新**：支持手动刷新 URL 数据源，自动追踪数据来源

#### 甘特图 (Gantt Chart)
- **简化 API**：新增 `scripts/gantt_chart.py`，提供简化的甘特图 API
- **任务数组输入**：只需提供任务名称、开始时间、结束时间即可生成甘特图
- **自动验证**：自动验证结束时间晚于开始时间
- **文档完善**：SKILL.md 新增甘特图使用场景和示例

#### 数据合并
- **多表合并**：新增 `scripts/data_merger.py`，支持将多个 DuckDB 表格合并为一个
- **来源追踪**：自动添加 `_source_table` 列追踪每行数据来源
- **导出支持**：支持将合并后的数据导出为 CSV 或 Excel 文件
- **CLI 命令**：提供命令行接口，支持 `--tables`、`--target`、`--export` 等参数

### 🛡️ 安全增强 (Security)

- **SQL 注入修复**：修复了 `data_exporter.py` 和 `data_cleaner.py` 中的 SQL 注入漏洞，使用表名白名单验证
- **输入验证**：新增 `validators.py`，使用 pydantic 对文件路径、表名、SQL 查询进行严格验证
- **API Key 安全**：将百度地图 API Key 从配置文件迁移到环境变量，弃用硬编码方式
- **路径遍历防护**：修复了 `server.py` 文件服务中的路径遍历漏洞，拒绝 `../` 等路径穿越尝试

### ⚡ 性能优化 (Performance)

- **连接池**：新增 `DatabaseRepository` 类，使用连接池管理 DuckDB 连接，支持自动清理
- **并发读取**：使用 DuckDB 支持本地分析型查询与多 Agent 读取场景
- **流式导入**：所有 Excel 文件使用流式导入，支持处理 100MB+ 大文件
- **分块处理**：Excel 导入使用 10,000 行/块的流式读取，平衡内存和性能
- **异步地理编码**：使用 httpx AsyncClient 实现异步地理编码 API 调用，支持 5 并发请求和指数退避重试
- **服务进程管理**：新增 PID 文件追踪和 5 分钟无活动自动关闭机制

### 📝 质量提升 (Quality)

- **测试覆盖**：新增 pytest 测试框架，核心模块测试覆盖率达到 80%+
- **结构化日志**：使用 structlog 替代所有 print() 语句，日志输出为 JSON 格式便于 AI Agent 解析
- **异常处理**：消除静默异常处理，所有异常都记录到日志文件
- **文档完善**：全面更新 SKILL.md、README.md，新增功能使用指南

### 📊 功能模块清单

| 功能 | 脚本 | 状态 |
|-----|------|------|
| 数据导入 | `data_importer.py` | ✅ 增强（流式导入、URL导入） |
| 数据导出 | `data_exporter.py` | ✅ 安全修复 |
| 图表生成 | `chart_generator.py` | ✅ 稳定 |
| 仪表盘生成 | `dashboard_generator.py` | ✅ 新增 |
| 甘特图生成 | `gantt_chart.py` | ✅ 新增 |
| 数据合并 | `data_merger.py` | ✅ 新增 |
| 数据清洗 | `data_cleaner.py` | ✅ 安全修复 |
| 本地服务 | `server.py` | ✅ 安全修复、进程管理 |
| 数据库管理 | `database.py` | ✅ 新增（连接池） |
| 验证器 | `validators.py` | ✅ 新增 |
| 日志配置 | `logging_config.py` | ✅ 新增 |
| 业务口径 | `metrics_manager.py` | ✅ 稳定 |
| 异步地理编码 | `async_geocoding.py` | ✅ 新增 |

### 🔧 技术债务清理

- 移除 `echarts_templates` 目录，转为纯 Prompt + JSON 参数生成模式
- 隔离 `outputs/` 目录，防止测试数据混入 Git
- 统一 CLI 命令风格，保持一致的参数命名

---

## 历史版本

### v0.9.0

* **图表地图彻底本地化（离线渲染）**
  * 新增中国全省份、直辖市及全球地图的离线 JS 资源 (`assets/echarts/*.js`)，彻底移除对外部 CDN 的强依赖。即使在无网络环境下，生成的中国地图、世界地图及各省份地图仍能完美呈现，彻底解决白屏问题。
  * `chart_generator.py` 现已支持自动侦测选项中的地域名称，并智能注入对应的本地地图资源文件。
* **精细维度地图的"AK 模式"回退机制**
  * 引入了强制的 **Map Fallback Rule**。当需要渲染城市级、街区级或小众国家的精细维度数据时（即本地静态 JS 无法覆盖的范围），自动回退并强制使用基于百度地图 API (bmap) 的渲染模式。
* **全面增强的数据导入能力**
  * 新增对 **WPS 数据文件 (`.et`)** 的原生支持。
  * 引入 `numbers-parser` 库，新增对 **Mac Numbers 文件 (`.numbers`)** 的原生支持。
  * 升级多工作表（Multi-Sheet）自动解析机制。现在导入 Excel/WPS/Numbers 文件时，将自动遍历所有 Sheet，并为每个 Sheet 在 DuckDB 中创建独立的表，表名自动规整化处理。
* **全新的一键导出功能**
  * 新增 `scripts/data_exporter.py` 脚本，支持将 DuckDB 数据库中的整表数据，或者执行特定 SQL 查询后的结果，一键导出为 `.csv` 或 `.xlsx` 格式。
* **业务口径管理能力**
  * 新增 `scripts/metrics_manager.py` 脚本与 `references/metrics.md` 知识库文件。支持随时追加和持久化保存用户的"统计口径"和"业务指标定义"，作为大模型生成精准 SQL 时的高质量上下文参考。

### 🛠️ 优化与修复 (Improvements & Fixes)

* **图表坐标系崩溃修复**：修复了在 ECharts 中尝试将饼图 (`pie`) 直接挂载到地理坐标系 (`geo`) 导致图表渲染崩溃白屏的问题，并在工作流中明确了必须使用 `scatter` 或 `effectScatter` 的规范。
* **百度 AK 类型错误规避**：针对百度地图服务报错状态码 `240` (APP 服务被禁用) 的问题，在规范中明确区分了"浏览器端 AK"与"服务端 AK"的使用场景，并提供了代码级的静态坐标 fallback 建议。
* **图表预览服务器资源泄漏修复**：重构了本地 HTTP Server 的启动检测机制。废弃了不可靠的本地临时状态文件，改为无状态的端口探测与专属健康检查接口 (`/__echart_skill_health`)。彻底解决了每次生成新图表时可能重复启动 Python 进程从而导致系统资源耗尽的严重 Bug，确保全局只复用一个轻量级 Server 实例。
* **图表生成引擎重构**：完全剥离了原有的冗余 ECharts Python 模板依赖（删除了 `echarts_templates` 目录），转为更加灵活和强大的纯 Prompt + 纯 JSON 参数生成模式，彻底解决了下钻图表返回时因对象绑定引发的报错（`TypeError: Cannot read properties of undefined`）。
* **隔离工作区输出**：更新了 `.gitignore` 和打包配置脚本 `package.sh`，强制隔离 `outputs/` 目录，防止测试数据或临时文件被错误地提交到 Git 仓库或打包到发布产物中。
* **文档完善**：全面更新了 `skill.md` 工作流指南与 `README.md`。新增了百度地图 API Key 的申请官方链接，并补充了未来功能迭代规划。
