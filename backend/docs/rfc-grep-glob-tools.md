# [RFC] 在 DeerFlow 中增加 `grep` 与 `glob` 文件搜索工具

## Summary

我认为这个方向是对的，而且值得做。

如果 DeerFlow 想更接近 Claude Code 这类 coding agent 的实际工作流，仅有 `ls` / `read_file` / `write_file` / `str_replace` 还不够。模型在进入修改前，通常还需要两类能力：

- `glob`: 快速按路径模式找文件
- `grep`: 快速按内容模式找候选位置

这两类工具的价值，不是“功能上 bash 也能做”，而是它们能以更低 token 成本、更强约束、更稳定的输出格式，替代模型频繁走 `bash find` / `bash grep` / `rg` 的习惯。

但前提是实现方式要对：**它们应该是只读、结构化、受限、可审计的原生工具，而不是对 shell 命令的简单包装。**

## Problem

当前 DeerFlow 的文件工具层主要覆盖：

- `ls`: 浏览目录结构
- `read_file`: 读取文件内容
- `write_file`: 写文件
- `str_replace`: 做局部字符串替换
- `bash`: 兜底执行命令

这套能力能完成任务，但在代码库探索阶段效率不高。

典型问题：

1. 模型想找 “所有 `*.tsx` 的 page 文件” 时，只能反复 `ls` 多层目录，或者退回 `bash find`
2. 模型想找 “某个 symbol / 文案 / 配置键在哪里出现” 时，只能逐文件 `read_file`，或者退回 `bash grep` / `rg`
3. 一旦退回 `bash`，工具调用就失去结构化输出，结果也更难做裁剪、分页、审计和跨 sandbox 一致化
4. 对没有开启 host bash 的本地模式，`bash` 甚至可能不可用，此时缺少足够强的只读检索能力

结论：DeerFlow 现在缺的不是“再多一个 shell 命令”，而是**文件系统检索层**。

## Goals

- 为 agent 提供稳定的路径搜索和内容搜索能力
- 减少对 `bash` 的依赖，特别是在仓库探索阶段
- 保持与现有 sandbox 安全模型一致
- 输出格式结构化，便于模型后续串联 `read_file` / `str_replace`
- 让本地 sandbox、容器 sandbox、未来 MCP 文件系统工具都能遵守同一语义

## Non-Goals

- 不做通用 shell 兼容层
- 不暴露完整 grep/find/rg CLI 语法
- 不在第一版支持二进制检索、复杂 PCRE 特性、上下文窗口高亮渲染等重功能
- 不把它做成“任意磁盘搜索”，仍然只允许在 DeerFlow 已授权的路径内执行

## Why This Is Worth Doing

参考 Claude Code 这一类 agent 的设计思路，`glob` 和 `grep` 的核心价值不是新能力本身，而是把“探索代码库”的常见动作从开放式 shell 降到受控工具层。

这样有几个直接收益：

1. **更低的模型负担**
   模型不需要自己拼 `find`, `grep`, `rg`, `xargs`, quoting 等命令细节。

2. **更稳定的跨环境行为**
   本地、Docker、AIO sandbox 不必依赖容器里是否装了 `rg`，也不会因为 shell 差异导致行为漂移。

3. **更强的安全与审计**
   调用参数就是“搜索什么、在哪搜、最多返回多少”，天然比任意命令更容易审计和限流。

4. **更好的 token 效率**
   `grep` 返回的是命中摘要而不是整段文件，模型只对少数候选路径再调用 `read_file`。

5. **对 `tool_search` 友好**
   当 DeerFlow 持续扩展工具集时，`grep` / `glob` 会成为非常高频的基础工具，值得保留为 built-in，而不是让模型总是退回通用 bash。

## Proposal

增加两个 built-in sandbox tools：

- `glob`
- `grep`

推荐继续放在：

- `backend/packages/harness/deerflow/sandbox/tools.py`

并在 `config.example.yaml` 中默认加入 `file:read` 组。

### 1. `glob` 工具

用途：按路径模式查找文件或目录。

建议 schema：

```python
@tool("glob", parse_docstring=True)
def glob_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    pattern: str,
    path: str,
    include_dirs: bool = False,
    max_results: int = 200,
) -> str:
    ...
```

参数语义：

- `description`: 与现有工具保持一致
- `pattern`: glob 模式，例如 `**/*.py`、`src/**/test_*.ts`
- `path`: 搜索根目录，必须是绝对路径
- `include_dirs`: 是否返回目录
- `max_results`: 最大返回条数，防止一次性打爆上下文

建议返回格式：

```text
Found 3 paths under /mnt/user-data/workspace
1. /mnt/user-data/workspace/backend/app.py
2. /mnt/user-data/workspace/backend/tests/test_app.py
3. /mnt/user-data/workspace/scripts/build.py
```

如果后续想更适合前端消费，也可以改成 JSON 字符串；但第一版为了兼容现有工具风格，返回可读文本即可。

### 2. `grep` 工具

用途：按内容模式搜索文件，返回命中位置摘要。

建议 schema：

```python
@tool("grep", parse_docstring=True)
def grep_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    pattern: str,
    path: str,
    glob: str | None = None,
    literal: bool = False,
    case_sensitive: bool = False,
    max_results: int = 100,
) -> str:
    ...
```

参数语义：

- `pattern`: 搜索词或正则
- `path`: 搜索根目录，必须是绝对路径
- `glob`: 可选路径过滤，例如 `**/*.py`
- `literal`: 为 `True` 时按普通字符串匹配，不解释为正则
- `case_sensitive`: 是否大小写敏感
- `max_results`: 最大返回命中数，不是文件数

建议返回格式：

```text
Found 4 matches under /mnt/user-data/workspace
/mnt/user-data/workspace/backend/config.py:12: TOOL_GROUPS = [...]
/mnt/user-data/workspace/backend/config.py:48: def load_tool_config(...):
/mnt/user-data/workspace/backend/tools.py:91: "tool_groups"
/mnt/user-data/workspace/backend/tests/test_config.py:22: assert "tool_groups" in data
```

第一版建议只返回：

- 文件路径
- 行号
- 命中行摘要

不返回上下文块，避免结果过大。模型如果需要上下文，再调用 `read_file(path, start_line, end_line)`。

## Design Principles

### A. 不做 shell wrapper

不建议把 `grep` 实现为：

```python
subprocess.run("grep ...")
```

也不建议在容器里直接拼 `find` / `rg` 命令。

原因：

- 会引入 shell quoting 和注入面
- 会依赖不同 sandbox 内镜像是否安装同一套命令
- Windows / macOS / Linux 行为不一致
- 很难稳定控制输出条数与格式

正确方向是：

- `glob` 使用 Python 标准库路径遍历
- `grep` 使用 Python 逐文件扫描
- 输出由 DeerFlow 自己格式化

如果未来为了性能考虑要优先调用 `rg`，也应该封装在 provider 内部，并保证外部语义不变，而不是把 CLI 暴露给模型。

### B. 继续沿用 DeerFlow 的路径权限模型

这两个工具必须复用当前 `ls` / `read_file` 的路径校验逻辑：

- 本地模式走 `validate_local_tool_path(..., read_only=True)`
- 支持 `/mnt/skills/...`
- 支持 `/mnt/acp-workspace/...`
- 支持 thread workspace / uploads / outputs 的虚拟路径解析
- 明确拒绝越权路径与 path traversal

也就是说，它们属于 **file:read**，不是 `bash` 的替代越权入口。

### C. 结果必须硬限制

没有硬限制的 `glob` / `grep` 很容易炸上下文。

建议第一版至少限制：

- `glob.max_results` 默认 200，最大 1000
- `grep.max_results` 默认 100，最大 500
- 单行摘要最大长度，例如 200 字符
- 二进制文件跳过
- 超大文件跳过，例如单文件大于 1 MB 或按配置控制

此外，命中数超过阈值时应返回：

- 已展示的条数
- 被截断的事实
- 建议用户缩小搜索范围

例如：

```text
Found more than 100 matches, showing first 100. Narrow the path or add a glob filter.
```

### D. 工具语义要彼此互补

推荐模型工作流应该是：

1. `glob` 找候选文件
2. `grep` 找候选位置
3. `read_file` 读局部上下文
4. `str_replace` / `write_file` 执行修改

这样工具边界清晰，也更利于 prompt 中教模型形成稳定习惯。

## Implementation Approach

## Option A: 直接在 `sandbox/tools.py` 实现第一版

这是我推荐的起步方案。

做法：

- 在 `sandbox/tools.py` 新增 `glob_tool` 与 `grep_tool`
- 在 local sandbox 场景直接使用 Python 文件系统 API
- 在非 local sandbox 场景，优先也通过 DeerFlow 自己控制的路径访问层实现

优点：

- 改动小
- 能尽快验证 agent 效果
- 不需要先改 `Sandbox` 抽象

缺点：

- `tools.py` 会继续变胖
- 如果未来想在 provider 侧做性能优化，需要再抽象一次

## Option B: 先扩展 `Sandbox` 抽象

例如新增：

```python
class Sandbox(ABC):
    def glob(self, path: str, pattern: str, include_dirs: bool = False, max_results: int = 200) -> list[str]:
        ...

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> list[GrepMatch]:
        ...
```

优点：

- 抽象更干净
- 容器 / 远程 sandbox 可以各自优化

缺点：

- 首次引入成本更高
- 需要同步改所有 sandbox provider

结论：

**第一版建议走 Option A，等工具价值验证后再下沉到 `Sandbox` 抽象层。**

## Detailed Behavior

### `glob` 行为

- 输入根目录不存在：返回清晰错误
- 根路径不是目录：返回清晰错误
- 模式非法：返回清晰错误
- 结果为空：返回 `No files matched`
- 默认忽略项应尽量与当前 `list_dir` 对齐，例如：
  - `.git`
  - `node_modules`
  - `__pycache__`
  - `.venv`
  - 构建产物目录

这里建议抽一个共享 ignore 集，避免 `ls` 与 `glob` 结果风格不一致。

### `grep` 行为

- 默认只扫描文本文件
- 检测到二进制文件直接跳过
- 对超大文件直接跳过或只扫前 N KB
- regex 编译失败时返回参数错误
- 输出中的路径继续使用虚拟路径，而不是暴露宿主真实路径
- 建议默认按文件路径、行号排序，保持稳定输出

## Prompting Guidance

如果引入这两个工具，建议同步更新系统提示中的文件操作建议：

- 查找文件名模式时优先用 `glob`
- 查找代码符号、配置项、文案时优先用 `grep`
- 只有在工具不足以完成目标时才退回 `bash`

否则模型仍会习惯性先调用 `bash`。

## Risks

### 1. 与 `bash` 能力重叠

这是事实，但不是问题。

`ls` 和 `read_file` 也都能被 `bash` 替代，但我们仍然保留它们，因为结构化工具更适合 agent。

### 2. 性能问题

在大仓库上，纯 Python `grep` 可能比 `rg` 慢。

缓解方式：

- 第一版先加结果上限和文件大小上限
- 路径上强制要求 root path
- 提供 `glob` 过滤缩小扫描范围
- 后续如有必要，在 provider 内部做 `rg` 优化，但保持同一 schema

### 3. 忽略规则不一致

如果 `ls` 能看到的路径，`glob` 却看不到，模型会困惑。

缓解方式：

- 统一 ignore 规则
- 在文档里明确“默认跳过常见依赖和构建目录”

### 4. 正则搜索过于复杂

如果第一版就支持大量 grep 方言，边界会很乱。

缓解方式：

- 第一版只支持 Python `re`
- 并提供 `literal=True` 的简单模式

## Alternatives Considered

### A. 不增加工具，完全依赖 `bash`

不推荐。

这会让 DeerFlow 在代码探索体验上持续落后，也削弱无 bash 或受限 bash 场景下的能力。

### B. 只加 `glob`，不加 `grep`

不推荐。

只解决“找文件”，没有解决“找位置”。模型最终还是会退回 `bash grep`。

### C. 只加 `grep`，不加 `glob`

也不推荐。

`grep` 缺少路径模式过滤时，扫描范围经常太大；`glob` 是它的天然前置工具。

### D. 直接接入 MCP filesystem server 的搜索能力

短期不推荐作为主路径。

MCP 可以是补充，但 `glob` / `grep` 作为 DeerFlow 的基础 coding tool，最好仍然是 built-in，这样才能在默认安装中稳定可用。

## Acceptance Criteria

- `config.example.yaml` 中可默认启用 `glob` 与 `grep`
- 两个工具归属 `file:read` 组
- 本地 sandbox 下严格遵守现有路径权限
- 输出不泄露宿主机真实路径
- 大结果集会被截断并明确提示
- 模型可以通过 `glob -> grep -> read_file -> str_replace` 完成典型改码流
- 在禁用 host bash 的本地模式下，仓库探索能力明显提升

## Rollout Plan

1. 在 `sandbox/tools.py` 中实现 `glob_tool` 与 `grep_tool`
2. 抽取与 `list_dir` 一致的 ignore 规则，避免行为漂移
3. 在 `config.example.yaml` 默认加入工具配置
4. 为本地路径校验、虚拟路径映射、结果截断、二进制跳过补测试
5. 更新 README / backend docs / prompt guidance
6. 收集实际 agent 调用数据，再决定是否下沉到 `Sandbox` 抽象

## Suggested Config

```yaml
tools:
  - name: glob
    group: file:read
    use: deerflow.sandbox.tools:glob_tool

  - name: grep
    group: file:read
    use: deerflow.sandbox.tools:grep_tool
```

## Final Recommendation

结论是：**可以加，而且应该加。**

但我会明确卡三个边界：

1. `grep` / `glob` 必须是 built-in 的只读结构化工具
2. 第一版不要做 shell wrapper，不要把 CLI 方言直接暴露给模型
3. 先在 `sandbox/tools.py` 验证价值，再考虑是否下沉到 `Sandbox` provider 抽象

如果按这个方向做，它会明显提升 DeerFlow 在 coding / repo exploration 场景下的可用性，而且风险可控。
