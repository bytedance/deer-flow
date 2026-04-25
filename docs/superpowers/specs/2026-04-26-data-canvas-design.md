# 数据分析画布功能设计文档

## 概述

在 DeerFlow 中新增数据分析画布功能，用户通过与 Agent 对话来规划和执行数据分析流程。画布以 DAG（有向无环图）形式展示数据分析组件，组件实例可执行读取数据、SQL 建表、Python 数据分析等操作。

## 设计目标

- 不修改现有功能，作为扩展模块添加
- Agent 全程参与设计和执行阶段
- 支持两种执行模式：交互式（Agent 可干预）和只读式（Agent 仅观察）
- 复用现有架构：thread 生命周期管理、沙箱执行、数据库连接池

## 架构方案

**方案二：Agent 扩展模式**

画布作为 Agent 的子能力，存储在 thread_data 中，Agent 通过专用工具操作画布。前端画布面板从右侧弹出，复用 artifacts 的 ResizablePanel 模式。

## 数据模型

### Canvas DAG 定义

存储路径：`.deer-flow/threads/{thread_id}/canvas/canvas.json`

```json
{
  "id": "canvas-001",
  "thread_id": "thread-abc",
  "name": "销售数据分析",
  "description": "分析月度销售数据并生成报表",
  "agent_execution_mode": "interactive",
  "nodes": [
    {
      "id": "node-1",
      "type": "data_source",
      "position": { "x": 100, "y": 100 },
      "data": {
        "connection_id": "conn-sales-db",
        "table_name": "sales_records"
      }
    },
    {
      "id": "node-2",
      "type": "sql_executor",
      "position": { "x": 300, "y": 100 },
      "data": {
        "sql": "CREATE TABLE temp_sales_clean AS SELECT * FROM {{node-1.connection_id}}.{{node-1.table_name}} WHERE amount > 0",
        "output_table": "temp_sales_clean"
      }
    },
    {
      "id": "node-3",
      "type": "python_script",
      "position": { "x": 500, "y": 100 },
      "data": {
        "script": "import pandas as pd\nimport os\n...",
        "input_tables": ["{{node-2.output_table}}"],
        "output_table": "temp_sales_result"
      }
    },
    {
      "id": "node-4",
      "type": "data_output",
      "position": { "x": 700, "y": 100 },
      "data": {
        "input_table": "{{node-3.output_table}}",
        "output_format": "csv",
        "filename": "sales_report.csv"
      }
    }
  ],
  "edges": [
    { "source": "node-1", "target": "node-2" },
    { "source": "node-2", "target": "node-3" },
    { "source": "node-3", "target": "node-4" }
  ],
  "status": "idle",
  "execution_log": [],
  "created_at": "2026-04-26T00:00:00Z",
  "updated_at": "2026-04-26T00:00:00Z"
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 画布唯一标识 |
| `thread_id` | string | 所属线程 ID |
| `name` | string | 画布名称 |
| `description` | string | 画布描述 |
| `agent_execution_mode` | enum | 执行模式：`interactive`（Agent 可干预）或 `readonly`（Agent 仅观察） |
| `nodes` | array | 节点列表 |
| `edges` | array | 边列表（定义节点间依赖关系） |
| `status` | enum | 画布状态：`idle`、`running`、`paused`、`completed`、`failed` |
| `execution_log` | array | 执行历史记录 |

## 组件类型

### 四种基础组件

| 组件类型 | 功能 | 配置参数 | 执行行为 |
|---------|------|---------|---------|
| **data_source** | 声明数据来源 | `connection_id`, `table_name` | 不执行操作，仅作为 DAG 起点 |
| **sql_executor** | 执行 SQL 建表 | `sql`, `output_table` | 执行 SQL（CREATE OR REPLACE TABLE），覆盖更新 |
| **python_script** | 执行 Python 脚本 | `script`, `input_tables`, `output_table` | 沙箱执行，读取输入表，输出到新表 |
| **data_output** | 导出数据到文件 | `input_table`, `output_format`, `filename` | 将表数据导出为 CSV/JSON 文件 |

### 数据传递机制

- 节点间通过 **表引用** 传递数据
- 使用 `{{node-X.field}}` 语法引用上游节点输出
- `data_source` 节点不建表，直接使用原始表
- `sql_executor` 和 `python_script` 节点输出临时表

### Python 脚本节点

沙箱执行环境提供：
- 预置库：pandas、numpy、sqlalchemy
- 环境变量：
  - `INPUT_TABLES`：输入表名列表（逗号分隔）
  - `OUTPUT_TABLE`：输出表名
  - `DB_URL`：数据库连接字符串

## Agent 工具

| 工具名称 | 功能 | 参数 |
|---------|------|------|
| **canvas_plan** | 规划数据分析 DAG | `description`, `context` |
| **canvas_add_node** | 添加节点 | `type`, `data`, `position`（可选） |
| **canvas_update_node** | 更新节点 | `node_id`, `data` |
| **canvas_delete_node** | 删除节点 | `node_id` |
| **canvas_add_edge** | 添加连线 | `source`, `target` |
| **canvas_delete_edge** | 删除连线 | `source`, `target` |
| **canvas_execute** | 执行画布 | 无参数 |
| **canvas_status** | 查询执行状态 | 无参数 |
| **canvas_node_result** | 查看节点执行结果 | `node_id` |
| **canvas_decide** | 决定下一步操作（仅 interactive 模式） | `action`, `reason`, `modifications`（可选） |
| **canvas_resume** | 恢复暂停的执行 | 无参数 |

## 执行引擎

### 执行模式

#### Readonly 模式
- 连续执行所有节点
- Agent 仅观察执行结果
- 不干预执行过程

#### Interactive 模式
- 每个节点执行后暂停
- Agent 分析结果并决策：
  - `continue`：继续执行下一个节点
  - `pause`：暂停，等待用户输入
  - `modify`：修改后续 DAG 配置，然后继续
  - `abort`：终止整个执行

### 执行流程

```
1. 用户/Agent 触发 canvas_execute
         │
         ▼
2. CanvasEngine 接收 Canvas DAG
         │
         ▼
3. 拓扑排序 → 确定执行顺序
         │
         ▼
4. 按顺序执行每个节点
    ├── 解析变量引用 ({{node-X.field}})
    ├── 获取组件执行器
    ├── 执行并记录结果
    ├── 发送节点结果给 Agent（custom event）
    └── interactive 模式：等待 Agent 决策
         │
         ▼
5. 全部完成或失败时返回结果
```

### 执行器接口

```python
class ComponentExecutor(ABC):
    """组件执行器基类"""
    
    @property
    @abstractmethod
    def node_type(self) -> str:
        pass
    
    @abstractmethod
    async def execute(
        self,
        node: CanvasNode,
        context: ExecutionContext
    ) -> NodeResult:
        pass
    
    def validate(self, node: CanvasNode) -> list[str]:
        return []

@dataclass
class ExecutionContext:
    canvas_id: str
    thread_id: str
    db_connections: dict[str, DatabaseConnection]
    sandbox: Sandbox
    resolved_variables: dict[str, Any]

@dataclass  
class NodeResult:
    success: bool
    output_table: str | None = None
    output_file: str | None = None
    rows_affected: int = 0
    error: str | None = None
    logs: list[str] = field(default_factory=list)
```

## 后端架构

### 目录结构

```
backend/
├── packages/harness/deerflow/
│   └── canvas/
│       ├── __init__.py
│       ├── models.py                # 数据模型定义
│       ├── components/
│       │   ├── __init__.py
│       │   ├── base.py              # 组件基类
│       │   ├── data_source.py
│       │   ├── sql_executor.py
│       │   ├── python_script.py
│       │   └── data_output.py
│       ├── engine.py                # DAG 执行引擎
│       ├── executor.py              # 节点执行器
│       └── tools.py                 # Agent 工具定义
│
└── app/gateway/routers/
    └── canvas.py                    # Canvas REST API
```

## 前端架构

### 面板集成方式

复用 artifacts 的 ResizablePanel 模式，画布面板从右侧弹出：

```
┌─────────────────────────────────────────────────────────────────────┐
│  Chat Page (ResizablePanelGroup)                                    │
│                                                                     │
│  ┌────────────────────────┐ ║ ┌───────────────────────────────────┐ │
│  │   Chat Panel           │ H │   Canvas Panel (右侧弹出)         │ │
│  │   (默认 100%)          │ a │   (激活时 40%)                    │ │
│  │                        │ n │                                   │ │
│  │   • 消息列表           │ d │   • React Flow DAG               │ │
│  │   • Agent 规划画布     │ l │   • 节点编辑器                   │ │
│  │   • 执行状态展示       │ e │   • 执行面板                     │ │
│  │                        │   │                                   │ │
│  └────────────────────────┘ ║ └───────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### 触发方式

- Agent 调用 `canvas_plan` 时自动打开画布面板
- 用户点击 header 中的 `CanvasTrigger` 按钮
- 画布面板可通过拖拽调整宽度

### 目录结构

```
frontend/src/
├── components/workspace/
│   ├── canvas/
│   │   ├── context.tsx              # CanvasContext
│   │   ├── canvas-trigger.tsx       # 触发按钮
│   │   ├── canvas-panel.tsx         # 画布面板
│   │   ├── canvas-toolbar.tsx       # 工具栏
│   │   ├── node-palette.tsx         # 组件拖拽面板
│   │   ├── nodes/                   # 自定义节点组件
│   │   │   ├── data-source-node.tsx
│   │   │   ├── sql-executor-node.tsx
│   │   │   ├── python-script-node.tsx
│   │   │   └── data-output-node.tsx
│   │   ├── node-editor.tsx          # 节点属性编辑面板
│   │   └── execution-status.tsx     # 执行状态展示
│   └── chats/
│       └── chat-box.tsx             # 扩展：添加 Canvas Panel
│
└── core/
    └── canvas/
        ├── types.ts                  # TypeScript 类型
        ├── api.ts                    # API 调用
        ├── hooks.ts                  # useCanvas, useCanvasExecute
        └── store.ts                  # 画布状态管理
```

## Gateway API

### 端点列表

| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/threads/{thread_id}/canvas` | GET | 获取画布数据 |
| `/api/threads/{thread_id}/canvas` | PUT | 保存画布数据 |
| `/api/threads/{thread_id}/canvas/execute` | POST | 执行画布 DAG |
| `/api/threads/{thread_id}/canvas/status` | GET | 获取执行状态 |
| `/api/threads/{thread_id}/canvas/resume` | POST | 恢复暂停的执行 |
| `/api/canvas/components` | GET | 获取可用组件列表 |
| `/api/database/connections` | GET | 获取数据库连接列表 |

### 响应模型

```python
class CanvasResponse(BaseModel):
    id: str
    thread_id: str
    name: str
    description: str
    agent_execution_mode: Literal["interactive", "readonly"]
    nodes: list[CanvasNode]
    edges: list[CanvasEdge]
    status: Literal["idle", "running", "paused", "completed", "failed"]
    execution_log: list[ExecutionLogEntry]

class ExecutionStatusResponse(BaseModel):
    canvas_id: str
    status: Literal["idle", "running", "paused", "completed", "failed"]
    current_node: str | None
    completed_nodes: list[str]
    pending_nodes: list[str]
    results: dict[str, NodeResult]

class ComponentResponse(BaseModel):
    type: str
    name: str
    description: str
    config_schema: dict  # JSON Schema

class DatabaseConnectionResponse(BaseModel):
    id: str
    name: str
    type: str
    host: str
    database: str
```

## 数据库连接管理

- 数据库连接在系统设置中预配置
- 存储在 `config.yaml` 或独立的 `database_connections.yaml`
- 敏感信息（密码）通过环境变量注入
- 画布中通过 `connection_id` 引用连接

## 开发阶段

### 阶段一：核心功能
- 后端：数据模型、执行引擎、Agent 工具
- 前端：画布面板基础结构、React Flow 集成
- 四种基础组件实现

### 阶段二：交互完善
- Interactive 模式完整实现
- 节点编辑器 UI
- 执行状态实时展示

### 阶段三：优化扩展
- 执行历史记录
- 节点模板库
- 性能优化

## 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| SQL 注入 | 使用参数化查询，限制 SQL 语句类型 |
| 沙箱逃逸 | 复用现有沙箱安全机制 |
| 数据库连接泄露 | 连接池管理，超时自动释放 |
| DAG 循环依赖 | 拓扑排序前检测循环 |
| 节点执行超时 | 配置超时时间，支持取消执行 |

## 依赖项

### 后端
- 无新增外部依赖，复用现有沙箱和数据库连接池

### 前端
- `@xyflow/react`：已有，用于 DAG 可视化
- `@radix-ui/react-*`：已有，用于 UI 组件
