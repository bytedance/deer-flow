# Agent 自演进扩展：设计与行为

本文说明扩展当前的工作方式、配置来源、安全边界和运行限制。
安装与授权示例见 [README](../README.md)，开发约定见 [AGENTS.md](../AGENTS.md)。
本文不记录本地部署状态、会话过程或随迭代变化的测试数量。

## 定位与模块边界

插件提供 Agent 自演进工作台，Skill 自演进是首个已实现的模块。
Memory 自演进目前仅展示为“规划中”，没有后台动作，也不继承 Skill 模块的权限。
未来模块应分别提供页面工厂、后台动作和明确的宿主授权。

为兼容已有安装、授权和历史数据，以下技术标识保持不变：

- 发行包：`deerflow-extension-skill-evolution`。
- Python 入口：`deerflow_extension_skill_evolution:install`。
- 插件命名空间：`community.skill-evolution`。
- 浏览器模块：`skill-evolution.v1`。

这些标识沿用 Skill 名称，不影响产品入口使用“Agent 自演进”。

## 两条演进入口

### Agent 在对话中沉淀经验

扩展通过 `SkillEvolutionContributor` 注册中间件，在 `before_agent` 或异步
`abefore_agent` 中向消息状态注入一条隐藏的 `SystemMessage`。相同消息 ID
已存在时不重复添加。默认只对主 Agent 生效，可通过 `scope` 扩大到子 Agent。

提示词建议 Agent 在复杂任务、用户纠正、排错或可复用工作流中考虑改进技能。
`min_tool_calls_hint: 5` 只是其中一条建议：**程序没有累计五次工具调用后自动
启动演进的计数器或调度器**，是否行动由当前对话模型判断。

若宿主旧内置演进功能 `skill_evolution.enabled` 仍开启，插件会抑制自己的重复策略提示；
迁移到插件时应关闭旧开关。

模型执行技能操作时使用宿主原有的 `skill_manage` 工具。该入口与页面的受控
变更入口不同，权限和具体操作规则由宿主工具执行。`prefer_patch` 和
`confirm_before_create` 是提示词要求，不是程序强制的修改限制或审批窗口。

相关实现：[prompt.py](../deerflow_extension_skill_evolution/prompt.py)、
[middleware.py](../deerflow_extension_skill_evolution/middleware.py)。

### 用户在页面上根据反馈生成草案

用户在技能使用轨迹的事件上保存标注，再选择一种方式生成草案：

- **模型**（`model`，默认）：点击“确认并优化”，启动后台模型任务；输入为当前
  SKILL.md 和该用户的反馈标注，输出为待审阅的完整 SKILL.md。
- **直接添加**（`append`）：点击“标注草案”，将尚未包含的反馈追加为
  `## Usage Feedback` 段落，不调用模型。

两种方式都不自动发布技能。用户审阅草案并暂存后，页面自动检查准确的
`proposal_id`，展示结论和原因码；手动“检查”按钮保留用于重试。
检查失败会保留已暂存的提案，只有 `allow` 结果才启用页面的提交按钮。
**发布仍需要用户明确点击“提交”，宿主也会重新验证检查结果与版本条件。**

相关实现：[drafts.py](../deerflow_extension_skill_evolution/drafts.py)、
[evolve.py](../deerflow_extension_skill_evolution/evolve.py)、
[mutations.py](../deerflow_extension_skill_evolution/mutations.py)。

## 权限与宿主职责

插件负责提示词、反馈标注、草案生成和页面交互；宿主负责受控变更的验证、扫描、
授权、版本冲突检测、发布、历史与回滚安全。插件不维护第二套宿主权限规则。

所有页面动作从宿主认证的 `principal.user_id` 获取调用者身份，不能通过请求体
指定另一个 owner。即使证据读取器能看到多用户运行，插件也会检查证据、提案和
操作的归属。取消后台任务前，必须先按 owner、skill 和 job_id 确认并删除对应记录，
未知或不匹配的 ID 不得中断任务。

所需授权来自运维控制的 `config.yaml → plugins[].host_access`：

- `skill_mutations`：限定可操作的用户、技能、动作与部署条件。
- `evidence`：提供已封存运行记录及事件读取能力。

页面的模型演进直接复用对话模型：模型列表来自 `/api/models`，请求以 `model_name`
提交所选模型名。默认使用当前用户可见列表中的第一个模型，不再维护插件独立的
模型角色或授权名单，也不需要额外的模型密钥。通用模型配置仍由宿主的对话配置提供。

Gateway 将 `ActionContext.chat_models` 绑定到当前浏览器用户，调用时复用普通对话的
`authorize_model_use` 与 `create_chat_model`，原有用户模型权限继续生效。显式关闭认证的
本地模式使用与对话一致的默认用户；PAT、内部调用和模型工具不会获得此能力。
模型请求仍受每个 Gateway、每个插件共享的并发（2）、排队、输入/输出额度和最多
120 秒超时保护；超时包含权限检查和等待模型容量的时间。停机时撤销句柄并取消调用者，
已经开始的 provider 工作在结束前仍占用容量。

旧 `host_access.model_invocation` 仅作为显式 `model_role` 服务调用的兼容路径保留，
页面不依赖它。这个通用入口由宿主提供，需要同时更新 Gateway，不能只更新插件资源。

“运行条件与权限”报告基础服务是否接通，不保证每次操作成功，也不表示允许修改
任意技能。协议、部署方式及旧版内置开关归入“高级诊断”。当前受控变更方案要求
受支持的 POSIX 单宿主、本地文件系统部署，不提供多 Gateway 故障切换保证。

## 配置来源与生效时机

### 运维配置

插件的 `plugins[].config` 保存行为建议、适用 Agent 范围和 `storage_path`。
`host_access` 保存授权。页面“插件配置”可以在用户位于变更授权 owners 列表时，
校验技能名并修改本插件的 `target_skills`，不写入模型配置。
已选技能在折叠项展开时置顶，保留尚未保存的选择。

配置文件编辑复用宿主的扩展管理器锁和局部写入逻辑。写入配置不等于运行中的
授权已经更新：应按页面提示重新安装扩展并重启 Gateway；仅调整宿主授权也需要
重启以重新绑定能力。旧 `feedback_mode` 只保留解析兼容，不再驱动演进方式。

### 用户选择的演进方式

`evolution_mode` 按调用实时读取，保存后立即生效，无需重启。
配置了 `storage_path` 时，设置文件与 SQLite 数据库同目录，以数据库文件名
区分不同安装实例。例如：

```text
storage_path: /data/evolution.sqlite
设置文件:    /data/evolution.sqlite.settings.json
文件内容:    {"evolution_mode": "model"}
```

可选值只有 `model` 和 `append`；文件缺失、损坏或值不合法时默认 `model`。
正常写入使用同目录私有临时文件和原子替换，保留其他 JSON 字段。
初始化时可复制仍存在的旧安装目录 `settings.json`，但不覆盖已有持久化文件。

**首次从旧版升级时，须在安装器替换旧包之前完成设置迁移**，否则旧文件可能先被
删除，初始化迁移就无法找到它。具体迁移命令见 [README](../README.md)。
迁移失败时应先处理告警并确认新文件已保存，再执行升级。
迁移成功后的设置不随插件包替换而丢失。

未配置 `storage_path` 时，继续使用安装目录文件作为兼容回退；这种情况下不能
保证升级后保留选择，反馈标注和演进记录存储也不可用。

相关实现：[configure.py](../deerflow_extension_skill_evolution/configure.py)、
[modes.py](../deerflow_extension_skill_evolution/modes.py)。

## 技能列表、轨迹与预热

### 展示范围

自演进技能列表返回当前用户通过受控管线保存的记录，并与宿主技能目录关联，
获取实时描述和启用状态。它不是全部可见技能的列表。
后端一次返回记录，前端每页显示 8 个技能；只有一页时不显示分页栏。
每个技能的版本列表最多返回最近 20 条历史。

每次轨迹查询最多返回 3 条激活过目标技能的运行。处理方式为：

1. 遍历宿主从旧到新的变更元数据 feed，保留最后 25 条元数据。
2. 倒序检查其中属于当前用户、已封存且来源和覆盖范围受支持的运行。
3. 读取事件，筛选真正激活过目标技能的运行，收集到 3 条即停止。

这里的“最近”按宿主变更顺序计算，25 条是元数据候选窗口，不能保证其中恰好有
3 条属于当前用户且使用了该技能的运行。自动发现变更来源使用同一分页逻辑，
候选窗口为 50 条。元数据扫描最多 200 页，游标异常或超限显式报错，不能将
未遍历到末尾的旧记录当作最新结果。快照与事件读取只针对候选窗口进行。

事件发现持续分页，直到找到目标技能的激活证据或运行记录结束；每页最多 100 条
事件、128 KiB。扫描最多 200 页，游标异常或超限显式报错，不能将未完成的发现
当作“未使用该技能”。返回时间线独立限制为最多 200 条可见事件，保留首个激活点
之前最多 100 条上下文，再收集后续事件；范围缩减时通过 `timeline_truncated`
提示用户查看完整对话。页面过滤系统噪声和没有文本的模型事件，预览最多
200 字符（截断时另加省略号）。

新增或编辑标注时，通过完整分页的运行元数据定位所引用的运行，再读取已封存证据。
运行必须属于当前用户，来源、覆盖范围和快照身份必须匹配；目标事件必须实际存在，
并且该运行必须记录过所选技能的激活。普通可见事件作为该次技能运行的上下文可供
标注，其他技能的激活事件和隐藏系统事件不可标注。此校验独立于展示窗口，允许
验证窗口外或较早运行中的事件。缺少证据、游标异常或扫描超限均拒绝写入；校验失败
不会保存反馈，也不会清理已有演进任务。删除仅操作当前用户自己的标注。

### 页面内预热与缓存

打开插件页面后，技能列表返回即开始预加载当前页和下一页的轨迹，与技能描述
请求并行。按每页 8 个计算，预热窗口最多覆盖 16 个技能。

- 最多两个轨迹请求并发，点击排队中的技能时提高其优先级；进行中的请求复用。
- 成功结果（包括空轨迹）缓存 60 秒，过期时先展示缓存，再后台更新。
- 初次预热尚未完成时仍可能等待；这不是 Gateway 启动时的全局预加载。
- 翻页后移动预热窗口，丢弃不再需要的推测性排队任务。
- 手动刷新会清空缓存并重新预热；标注保存或删除会强制更新对应技能。
- 旧请求的迟到结果不能覆盖新请求的数据；后台完成也不能重置正在编辑的标注。
- 失败结果有 5 秒重试冷却；遇到权限错误时丢弃旧内容。

缓存属于当前认证页面，只保存在内存，不写入 localStorage，不跨用户共享。
缓存以 32 项为保留目标，优先淘汰较久未使用的已完成项；加载中的任务另外受并发
和窗口控制。页面卸载后清空缓存、停止排队任务并忽略迟到响应，不能取消宿主
已经收到的 action。

相关实现：[trajectories.py](../deerflow_extension_skill_evolution/trajectories.py)、
[recent_runs.py](../deerflow_extension_skill_evolution/recent_runs.py)、
[trajectory-cache.mjs](../deerflow_extension_skill_evolution/static/trajectory-cache.mjs)。

## 反馈去重、任务状态与版本

append 草案用隐藏 Markdown 标记记录 owner、技能、完整 run/event ID 和去除首尾空白后
标注文本的 SHA-256 指纹。重复保存相同标注不会重复追加，编辑文本后可以再次
进入草案。旧版没有标记的反馈仅在完整渲染条目精确匹配时视为已包含。
先去重，再按最多 20 条和反馈段大小预算选择标注。

去重依据是**当前技能实际包含的内容**，不是生成草案时就将标注标记为已消费：
未发布前重复生成同一草案应得到相同内容；回滚移除了反馈后，对应标注重新可用。
`already_included_count` 与本次 `included_count` 分开返回。手动编辑技能时应保留
来源标记，以维持可靠去重。

模型任务按 owner 和 skill 限制最多一个 running 记录。模型只返回草案，完整的一层
Markdown 包装可移除，正文中的多个代码块必须保留。页面区分：

- 已生成草案：展示当前内容与草案的差异，等待用户暂存。
- 无变更：模型保持输入内容不变，不表示发生了发布。
- 已发布：草案匹配后续的版本提交；还要检查提交时间，不能仅比较文本相同。
- 失败：返回稳定错误码，不把内部异常或宿主路径展示给模型或页面。

新增或编辑标注后，已发布或无变更的任务记录会自动清理；待处理草案和失败记录
保留。SQLite 时间戳采用 UTC，排查任务与发布先后顺序时应使用相同时间基准。
时间戳只有秒级精度，同秒匹配提交采用兼容处理，不能提供更细的事件排序保证。

后台任务是进程内任务，Gateway 重启后不会自动恢复执行。再次启动演进时会将
超过 30 分钟的 running 记录标记为过期失败；也可在页面清除旧记录后重试。
这不等于多进程任务接管或分布式恢复。

相关实现：[evolved.py](../deerflow_extension_skill_evolution/evolved.py)、
[evolve.py](../deerflow_extension_skill_evolution/evolve.py)。

## 验证与维护

从仓库根目录执行以下离线检查：

```bash
PYTHONPATH=examples/deerflow-extension-skill-evolution \
  backend/.venv/bin/python -m pytest examples/deerflow-extension-skill-evolution/tests -q
node --test examples/deerflow-extension-skill-evolution/tests/test_*.mjs
backend/.venv/bin/ruff check examples/deerflow-extension-skill-evolution
backend/.venv/bin/ruff format --check examples/deerflow-extension-skill-evolution
```

重点回归边界包括用户隔离、取消任务前鉴权、元数据分页与预算、自动检查与手动
提交、对话模型复用与用户权限、Markdown 内容保留、旧设置迁移、append 去重，以及预热的
并发、缓存失效和卸载行为。界面验证使用隔离的模拟响应，避免修改生产技能与授权。

维护本文时以当前实现为准，不将已经解决的问题继续列为待办，也不记录本地
提交状态、临时任务 ID、模型实例名或一次会话的排查时间线。
