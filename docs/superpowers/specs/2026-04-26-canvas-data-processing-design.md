# Canvas 数据处理流程设计文档

> 创建日期：2026-04-26

## 概述

Canvas 是 DeerFlow 的数据分析工作流功能，允许用户通过可视化 DAG（有向无环图）构建数据处理流程，用于报表生成场景。用户通过拖拽组件、配置节点、执行流程，最终生成数据报表文件。

## 目标场景

- **报表生成**：用户定义数据源和SQL查询，系统执行后生成报表文件
- 支持从 `config.yaml` 配置的数据库连接选择数据源
- 支持查看中间执行结果和数据预览

## 架构设计

### 整体布局

```
┌──────────────────────────────────────────────────────────────┐
│  Canvas Toolbar                                              │
│  [名称] | [编辑/运行切换] [执行] [保存] [清空结果]              │
├────────┬─────────────────────────────────┬───────────────────┤
│组件面板 │                                 │                   │
│        │                                 │  节点编辑器        │
│[拖拽源] │     React Flow DAG              │  (选中节点时显示)  │
│        │                                 │                   │
│        │                                 ├───────────────────┤
│        │                                 │                   │
│        │                                 │  结果预览面板      │
│        │                                 │  (始终可见)        │
└────────┴─────────────────────────────────┴───────────────────┘
```

### 状态机

```
┌─────────┐    Execute    ┌─────────┐
│  编辑态  │ ────────────▶│  运行态  │
│ (edit)  │               │ (run)   │
└─────────┘◀──────────── └─────────┘
              Complete/Stop
```

**编辑态**：
- 可拖拽添加节点
- 可编辑节点配置
- 可删除节点/边
- 可调整节点位置

**运行态**：
- 锁定画布操作
- 实时显示执行进度
- 工具栏按钮变为"停止执行"

**状态切换**：
- 工具栏有明确的"编辑/运行"切换按钮
- 执行完成后自动回到编辑态
- 运行中切换回编辑态需确认停止

## 节点类型

### 1. Data Source 节点

**用途**：声明数据来源（数据库表）

**配置项**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| display_name | 文本 | 否 | 节点显示名称 |
| connection_id | 下拉选择 | 是 | 从 `db_connections` 选择 |
| table_name | 下拉选择 | 是 | 根据连接动态加载表列表 |

**功能**：
- 选择表后显示表结构预览（字段名、类型）
- 提供"预览数据"按钮，显示前100行

**节点显示**：
- 标题：Data Source
- 摘要：表名或 display_name
- 输出端口：1个（source）

### 2. SQL Executor 节点

**用途**：执行SQL查询，输出结果表

**配置项**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| display_name | 文本 | 否 | 节点显示名称 |
| output_table | 文本 | 是 | 输出表名 |
| sql | 多行文本 | 是 | SQL语句（弹窗编辑） |

**变量引用**：
- 支持 `{{node-X.output_table}}` 引用上游节点输出
- 变量列表在弹窗编辑器顶部显示
- 点击变量名可快速插入

**验证**：
- 提供"验证SQL"按钮，检查语法
- 验证时替换变量后执行 EXPLAIN

**节点显示**：
- 标题：SQL Executor
- 摘要：display_name 或 output_table
- 输入端口：1个（target）
- 输出端口：1个（source）

### 3. Python Script 节点

**用途**：执行Python代码处理数据

**配置项**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| display_name | 文本 | 否 | 节点显示名称 |
| input_tables | 多选标签 | 是 | 选择上游节点输出 |
| output_table | 文本 | 是 | 输出表名 |
| script | 多行文本 | 是 | Python代码（弹窗编辑） |

**代码约定**：
- 输入通过 `input_tables` 列表访问
- 需返回 pandas DataFrame

**节点显示**：
- 标题：Python Script
- 摘要：display_name 或 output_table
- 输入端口：1个（target）
- 输出端口：1个（source）

### 4. Data Output 节点

**用途**：导出数据到文件

**配置项**：
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| display_name | 文本 | 否 | 节点显示名称 |
| input_table | 下拉选择 | 是 | 从上游节点选择 |
| output_format | 下拉选择 | 是 | csv / json |
| filename | 文本 | 是 | 输出文件名 |

**节点显示**：
- 标题：Data Output
- 摘要：display_name 或 filename
- 输入端口：1个（target）
- 无输出端口

## 节点编辑器

### 右侧面板编辑器（精简配置）

对于所有节点类型，右侧面板只显示基础配置项：
- 显示名称
- 输出表名（如适用）
- 状态指示（已编辑/未编辑）
- 编辑按钮

### 弹窗编辑器（SQL/Python）

**触发**：点击右侧面板的"编辑SQL语句"或"编辑Python代码"按钮

**布局**：
```
┌────────────────────────────────────────────────────────┐
│ 编辑 SQL 语句                                    [×]  │
├────────────────────────────────────────────────────────┤
│ 可用变量:                                              │
│  • {{node-1.output_table}} - Data Source (sales)      │
│  • {{node-2.output_table}} - SQL Executor (result)    │
│  点击变量名可快速插入                                   │
├────────────────────────────────────────────────────────┤
│                                                        │
│ ┌──────────────────────────────────────────────────┐  │
│ │SELECT ...                                        │  │
│ │FROM {{node-1.output_table}}                      │  │
│ │...                                               │  │
│ └──────────────────────────────────────────────────┘  │
│                                                        │
├────────────────────────────────────────────────────────┤
│                              [取消]  [保存并关闭]      │
└────────────────────────────────────────────────────────┘
```

**特性**：
- 弹窗尺寸：宽度约80%，高度约60%屏幕
- SQL编辑器：关键字语法高亮
- Python编辑器：基础语法高亮
- ESC键或点击×关闭
- 保存后更新节点状态

## 组件面板

**位置**：左侧，可折叠

**布局**：
```
┌────────────┐
│ 组件       │
├────────────┤
│ ▼ 数据源   │
│   ┌──────┐ │
│   │📊Data│ │
│   │Source│ │
│   └──────┘ │
├────────────┤
│ ▼ 处理     │
│   ┌──────┐ │
│   │📝SQL │ │
│   │Exec  │ │
│   └──────┘ │
│   ┌──────┐ │
│   │🐍Py  │ │
│   │Script│ │
│   └──────┘ │
├────────────┤
│ ▼ 输出     │
│   ┌──────┐ │
│   │📁Data│ │
│   │Output│ │
│   └──────┘ │
└────────────┘
```

**交互**：
- 拖拽组件到画布添加节点
- 新节点出现在鼠标释放位置
- 自动生成节点ID（递增）

## 执行结果面板

**位置**：右侧下方，始终可见

### 编辑态显示

```
┌─────────────────────────┐
│ 执行结果                 │
├─────────────────────────┤
│ 状态: ✓ 完成             │
│ 耗时: 3.2s              │
├─────────────────────────┤
│ 节点执行历史:            │
│ ├─ node-1 ✓ 0.5s        │
│ ├─ node-2 ✓ 1.8s        │
│ └─ node-3 ✓ 0.9s        │
├─────────────────────────┤
│ 选中节点结果 (node-2):   │
│                         │
│ 输出表: monthly_sales   │
│ 行数: 12                │
│                         │
│ [预览数据] [下载CSV]     │
└─────────────────────────┘
```

### 运行态显示

```
┌─────────────────────────┐
│ 执行中...               │
├─────────────────────────┤
│ 进度: 2/3 节点          │
│ ████████░░░░ 67%        │
├─────────────────────────┤
│ [时间戳] 开始执行...    │
│ [时间戳] node-1 完成 ✓  │
│ [时间戳] node-2 执行中  │
│ [时间戳] ...            │
└─────────────────────────┘
```

### 数据预览弹窗

点击"预览数据"后弹出：

```
┌─────────────────────────────────────┐
│ 数据预览 - monthly_sales      [×]   │
├─────────────────────────────────────┤
│ │ month   │ total_sales │ count │   │
│ ├────────┼──────────────┼───────┤   │
│ │ 2024-01│ 152340.00    │ 245   │   │
│ │ 2024-02│ 189200.50    │ 312   │   │
│ │ ...    │ ...          │ ...   │   │
│ └────────┴──────────────┴───────┘   │
│ 显示前100行，共12行                  │
└─────────────────────────────────────┘
```

## API 设计

### 数据库连接

```
GET /api/db-connections
Response: {
  connections: [
    { id: string, name: string, type: string }
  ]
}

GET /api/db-connections/{connection_id}/tables
Response: { tables: string[] }

GET /api/db-connections/{connection_id}/tables/{table_name}/schema
Response: {
  columns: [{ name: string, type: string, nullable: boolean }]
}

GET /api/db-connections/{connection_id}/tables/{table_name}/preview?limit=100
Response: { rows: object[], total_rows: number }
```

### Canvas 操作

```
GET /api/threads/{thread_id}/canvas
PUT /api/threads/{thread_id}/canvas
DELETE /api/threads/{thread_id}/canvas

POST /api/threads/{thread_id}/canvas/execute
Body: { db_connections?: Record<string, object> }
Response: ExecutionStatusResponse

GET /api/threads/{thread_id}/canvas/status
Response: ExecutionStatusResponse

POST /api/threads/{thread_id}/canvas/stop
Response: { success: true }

GET /api/threads/{thread_id}/canvas/nodes/{node_id}/preview?limit=100
Response: { rows: object[], columns: object[], rows_count: number }

POST /api/threads/{thread_id}/canvas/validate-sql
Body: { sql: string }
Response: { valid: boolean, resolved_sql?: string, errors: string[] }

GET /api/canvas/components
Response: { components: ComponentInfo[] }
```

### 响应模型

```typescript
interface ExecutionStatusResponse {
  canvas_id: string;
  status: 'idle' | 'running' | 'paused' | 'completed' | 'failed';
  current_node: string | null;
  completed_nodes: string[];
  pending_nodes: string[];
  results: Record<string, NodeResult>;
}

interface NodeResult {
  success: boolean;
  output_table: string | null;
  output_file: string | null;
  rows_affected: number;
  error: string | null;
  logs: string[];
}
```

## 执行流程

```
用户点击Execute
    │
    ▼
前端: setCanvasMode('run')
前端: POST /api/threads/{thread_id}/canvas/execute
    │
    ▼
后端: CanvasEngine.execute()
    │   1. 拓扑排序节点
    │   2. 解析变量引用
    │   3. 按序执行各节点
    │   4. 记录执行日志
    │
    ▼
前端轮询: GET .../canvas/status (每1秒)
    │
    ▼
前端更新: executionStatus, nodeResults
前端渲染: 节点进度高亮，日志滚动
    │
    ▼
执行完成: status = 'completed' 或 'failed'
前端: setCanvasMode('edit')
```

## 验证规则

### 节点验证

| 节点类型 | 验证规则 |
|---------|---------|
| Data Source | connection_id、table_name 必填；连接和表可访问 |
| SQL Executor | output_table 必填且不与上游重名；sql 必填 |
| Python Script | output_table 必填；script 必填；input_tables 非空 |
| Data Output | input_table、filename、output_format 必填 |

### DAG 验证

- 保存时检测循环依赖
- 无孤立节点（所有节点有路径连通）
- 执行前验证所有节点配置完整

## 错误处理

### 单节点失败

- 停止后续执行
- 显示错误详情
- 节点标记红色失败状态
- 允许修改后重新执行

### 连接失败

- Data Source 节点显示具体错误
- 提示检查连接配置

### 超时处理

- 单节点默认超时：5分钟
- 超时后标记失败

### 状态切换保护

- 运行态→编辑态：提示确认停止
- 编辑态→运行态：未保存时提示保存

## 文件存储

- Canvas 数据：`{base_dir}/canvas/{thread_id}.json`
- 输出文件：`{base_dir}/threads/{thread_id}/outputs/{filename}`

## 前端状态管理

```typescript
interface CanvasContextType {
  // 基础状态
  canvas: Canvas | null;
  setCanvas: (canvas: Canvas | null) => void;
  open: boolean;
  setOpen: (open: boolean) => void;
  
  // 选择状态
  selectedNodeId: string | null;
  selectNode: (nodeId: string | null) => void;
  selectedNodes: string[];
  setSelectedNodes: (nodes: string[]) => void;
  selectedEdges: string[];
  setSelectedEdges: (edges: string[]) => void;
  
  // 模式状态
  canvasMode: 'edit' | 'run';
  setCanvasMode: (mode: 'edit' | 'run') => void;
  isEditing: boolean;
  setIsEditing: (editing: boolean) => void;
  
  // 执行状态
  executionStatus: ExecutionStatusResponse | null;
  setExecutionStatus: (status: ExecutionStatusResponse | null) => void;
  nodeResults: Record<string, NodeResult>;
  setNodeResults: (results: Record<string, NodeResult>) => void;
  
  // 数据源
  dbConnections: DbConnection[];
  setDbConnections: (connections: DbConnection[]) => void;
}
```
