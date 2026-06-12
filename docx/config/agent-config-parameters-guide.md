# DeerFlow Agent 配置参数完整指南

> 本文档汇总了对 `config.yaml` / `config.example.yaml` 关键参数的逐项分析、源码追溯、影响说明与调参建议。覆盖：summarization、loop_detection、models、subagents、memory、recursion_limit、sandbox、circuit_breaker 等所有影响 Agent 工作的参数。
>
> 调研基础：源码 `backend/packages/harness/deerflow/config/*.py` 及 `backend/packages/harness/deerflow/agents/middlewares/*.py`，以及上游 langchain `agents/middleware/summarization.py`。

---

## 目录

1. [Summarization 参数详解](#一summarization-参数详解)
2. [fraction trigger 的关键坑](#二fraction-trigger-的关键坑)
3. [Loop Detection 参数详解](#三loop-detection-参数详解)
4. [影响 Agent 行为的参数地图（Tier 分级）](#四影响-agent-行为的参数地图tier-分级)
5. [一句话决策清单](#五一句话决策清单)

---

## 一、Summarization 参数详解

### 1.1 参数语义

源码位置：`backend/packages/harness/deerflow/config/summarization_config.py:21`

| 参数 | 作用 | 何时介入 |
|---|---|---|
| `enabled` | 总开关 | 关掉则中间件不挂载 |
| `model_name` | 用哪个模型做摘要；`null` = 复用当前 lead 模型 | 想省钱可指向便宜的小模型 |
| `trigger.type=tokens, value=N` | 当对话总 token ≥ N 时触发摘要 | 这是"整段历史"的 token，不是单次输出 |
| `keep.type=messages, value=N` | 保留最近 N 条消息原文，前面的去做摘要 | 决定"近的细节保多少" |
| `trim_tokens_to_summarize: N` | 调用摘要模型时，喂给它的输入最多 N token，多余截断 | 防止"摘要请求本身"超出上下文 |
| `summary_prompt` | 自定义摘要提示词模板；`null` = 用 LangChain 默认 | 一般不动 |
| `preserve_recent_skill_count: 5` | 摘要时抢救最近 5 次 skill 文件读取，不让它们被压缩掉 | 避免 agent"忘记"刚加载的 SKILL.md 内容 |
| `preserve_recent_skill_tokens: N` | 抢救 skill 读取的总 token 预算 | 超出就不再抢救更多 skill |
| `preserve_recent_skill_tokens_per_skill: N` | 单个 skill 读取的抢救上限，超过的整块放弃 | 防止一个超大 SKILL.md 吃光预算 |
| `skill_file_read_tool_names` | 哪些工具名算作"读 skill 文件" | 接入新的文件读取工具时再加 |

### 1.2 关键的不自洽陷阱

**`preserve_recent_skill_tokens` 必须远小于 `trigger.tokens`**，否则：
- 设定"对话到 X token 就触发摘要"
- 又说"摘要时最多保留 25K 的 skill 内容"
- 结果触发了摘要也压不下去，每次都白跑一遍

经验值：`preserve_recent_skill_tokens` ≤ `trigger.tokens` × 25%。

### 1.3 `max_tokens` ≠ context window 的概念区分

`models[*].max_tokens` 是模型**单次输出**的上限（生成多少 token），**不是上下文窗口**（context window，输入+输出的总容量）。摘要触发用的是"总上下文"，所以真正要参考的是模型的 context window：

| 模型 | context window |
|---|---|
| MiniMax M-系列 | 通常 ~245K |
| DeepSeek V4 | 通常 ~128K |
| Qwen3.6-27B | 通常 ~128K |
| Claude（MiniMax-M3 走的也是 Claude） | ~200K |

### 1.4 推荐配置：DeepSeek V4 Flash (128K context, 4096 输出)

```yaml
summarization:
  enabled: true
  model_name: null                  # 可选：指向更大模型（如 MiniMax-M3）专做摘要
  trigger:
  - type: tokens
    value: 96000                    # 75% × 128K，保持不变（每轮更短，触发更稀疏）
  keep:
    type: messages
    value: 14                       # 每轮输出 ≤4K，多保 2 条不亏
  trim_tokens_to_summarize: 40000   # 匹配 4K 输出 → 10× 压缩，质量稳
  summary_prompt: null
  preserve_recent_skill_count: 5
  preserve_recent_skill_tokens: 20000
  preserve_recent_skill_tokens_per_skill: 5000
  skill_file_read_tool_names:
  - read_file
  - read
  - view
  - cat
```

### 1.5 压缩比 trade-off

| `trim_tokens_to_summarize` | 输入/输出比 | 含义 |
|---|---|---|
| 80000 | 80K → 4K = **20×** | 模型几乎是"凭印象写大纲"，细节大量丢失（不推荐） |
| 60000 | 60K → 4K = **15×** | 高层叙事尚可，关键事实开始模糊（偏激进） |
| **40000** | 40K → 4K = **10×** | **质量最稳的甜点**，足以保留任务脉络与关键决策（推荐） |
| 30000 | 30K → 4K = 7.5× | 高质量摘要，但更多远古消息会被直接截断 |

**注意**：超过 `trim_tokens_to_summarize` 的最老消息**不是被摘要，而是被直接丢弃**。所以这个值同时是"能被回顾到的最老历史边界"。

### 1.6 不同 context window 的线性放大

| Context Window | trigger.tokens | trim_tokens_to_summarize | skill 预算 |
|---|---|---|---|
| ~32K | 24000 | 18000-20000 | 6000-8000 |
| ~128K | 96000 | 40000 (4K out) / 80000 (8K out) | 20000 |
| ~200K+ | 150000 | 130000 | 30000-40000 |

---

## 二、fraction trigger 的关键坑

### 2.1 `fraction: 0.8` 是什么

源码：`langchain/agents/middleware/summarization.py:401-409`

```python
if kind == "fraction":
    max_input_tokens = self._get_profile_limits()  # 读 model.profile["max_input_tokens"]
    threshold = int(max_input_tokens * value)       # 例如 128000 × 0.8 = 102400
    if total_tokens >= threshold:
        return True
```

意思：**当对话总 token ≥ 模型 max_input_tokens × 0.8 时触发摘要**。

### 2.2 三种 trigger 类型对比

| 类型 | 写法 | 触发条件 | 优点 | 缺点 |
|---|---|---|---|---|
| `tokens` | `value: 96000` | 绝对 token 数 ≥ 96000 | 明确、可控 | 换模型要手动改 |
| `messages` | `value: 50` | 消息条数 ≥ 50 | 简单 | 不感知消息大小，不准 |
| `fraction` | `value: 0.8` | 占模型 max_input_tokens 80% | **跨模型自动缩放** | 依赖模型自报 profile |

### 2.3 在 DeerFlow 里 fraction 会直接启动失败

源码 `__init__` 校验（`summarization.py:279-290`）：
```python
requires_profile = any(condition[0] == "fraction" for condition in self._trigger_conditions)
if requires_profile and self._get_profile_limits() is None:
    raise ValueError("Model profile information is required to use fractional token limits, ...")
```

而 `_get_profile_limits()` 从 `self.model.profile["max_input_tokens"]` 取数（`summarization.py:476-491`）。

**实测验证**：

| 模型 | 是否提供 `profile["max_input_tokens"]` |
|---|---|
| `PatchedChatDeepSeek` | ❌ 没有 |
| `PatchedChatMiniMax` | ❌ 没有 |
| `ClaudeChatModel` | ❌ 没有 |
| `VllmChatModel` | ❌ 没有 |
| `langchain_deepseek` 上游 | ❌ 没有 |
| `langchain_openai`（如 gpt-4o 系列） | ✅ 有 |

**结论**：DeerFlow 当前自带的 patched provider 都没塞 profile，**反注释 `fraction: 0.8` 会让 lead agent 启动时直接抛 ValueError**。

### 2.4 想用 fraction 怎么办

两条路（都涉及改代码，不推荐）：
1. 在 patched provider 的 `__init__` 里塞 `self.profile = {"max_input_tokens": 128000}`
2. 改 `models/factory.py` 根据 `config.yaml` 新增字段统一注入 profile

**实际建议**：保持 `type: tokens` 不动。`config.example.yaml` 那几行注释展示的是 langchain 上游能力，不代表 DeerFlow 已经接通。

---

## 三、Loop Detection 参数详解

### 3.1 一句话理解

**Loop detection 是给 agent 装的"防卡死保险丝"**。AI agent 偶尔会陷入死循环——同样的事干 10 遍 50 遍停不下来。这套参数决定：什么时候提醒它"你在重复"，什么时候直接掐断它。

### 3.2 两套独立的检测机制

#### A 套：抓"同一件事重复做"
源码：`loop_detection_middleware.py:142-160`

```
warn_threshold: 3    ← 同一个调用做 3 次 → 警告
hard_limit: 5        ← 同一个调用做 5 次 → 强停
window_size: 20      ← 只看最近 20 步，更早的忘掉
```

工作方式：
- 每轮模型响应后，对 tool calls 做 `(name + 关键参数)` 哈希
- 维护一个长度 `window_size` 的滑动窗口
- 同一个哈希出现 `warn_threshold` 次 → 注入警告
- 出现 `hard_limit` 次 → 剥掉所有 tool_calls，强迫模型出最终答案

关键参数提取（`_stable_tool_key`）：
- `read_file`：按 `path + 行号桶（200 行一桶）` 哈希 → 读 1-100 和 200-400 算两次不同调用
- `write_file` / `str_replace`：全参数哈希（同一文件改不同内容算不同调用）
- 其他工具：只看 `path/url/query/command/pattern/glob/cmd` 这几个关键字段

#### B 套：抓"某类工具叫太多次"

```
tool_freq_warn: 30        ← 任何一种工具叫到 30 次 → 警告
tool_freq_hard_limit: 50  ← 叫到 50 次 → 强停
```

工作方式：
- 不看参数，只看**工具名**的累计调用次数（per-run）

**为什么需要 B**：哈希检测漏掉"读 30 个不同文件"这种 cross-file loop——每次哈希都不同，A 抓不到，B 兜底。

### 3.3 它在防什么具体场景

| Agent 在干嘛 | 哪个参数会救场 |
|---|---|
| 一直 `bash("ls /tmp")` 反复执行同一条命令 | warn_threshold / hard_limit |
| 一直 `read_file("/etc/passwd")` 反复读同一文件 | warn_threshold / hard_limit |
| 在代码库里读了 80 个不同文件还在读 | tool_freq_warn / tool_freq_hard_limit |
| 同一段代码 str_replace 来回改 | warn_threshold / hard_limit |

**如果没有这套机制**：agent 会一直跑到 LangGraph 的最大递归限制（默认 25 步）才停，期间烧的 token 全是你的钱。

### 3.4 硬约束（启动会校验）

```python
hard_limit >= warn_threshold              # 必须
tool_freq_hard_limit >= tool_freq_warn   # 必须
所有值 >= 1
```

### 3.5 调大调小的影响

| 调整 | 后果 |
|---|---|
| `warn_threshold` 调到 **2**（更紧） | 第 2 次同样调用就警告。偶尔误伤（agent 只是验证一下） |
| `warn_threshold` 调到 **5**（更松） | 多放几次再警告。真死循环时多烧几轮 token |
| `tool_freq_warn` 调到 **15** | 凡是用某工具超过 15 次就唠叨。研究代码库时经常被打断 |
| `tool_freq_warn` 调到 **60** | 给 agent 更多空间做批量操作。死循环要烧更久才发现 |
| `tool_freq_hard_limit` 调到 **25** | 任务做到一半被强停的概率上升 |
| `tool_freq_hard_limit` 调到 **100** | 给 agent 大量空间。真有问题时浪费多 |

### 3.6 按场景三套配置

#### 场景 1：默认通用（当前 = 代码默认值，合理）

```yaml
loop_detection:
  enabled: true
  warn_threshold: 3
  hard_limit: 5
  window_size: 20
  max_tracked_threads: 100
  tool_freq_warn: 30
  tool_freq_hard_limit: 50
```

#### 场景 2：编码/研究/批处理 agent（最常见的优化方向）

**核心做法：A 层保持紧，B 层放松，给高频工具单独开洞**

```yaml
loop_detection:
  enabled: true
  warn_threshold: 3            # A 层保持紧
  hard_limit: 5
  window_size: 20
  max_tracked_threads: 100
  tool_freq_warn: 50           # B 层全局放松
  tool_freq_hard_limit: 80
  tool_freq_overrides:         # 高频工具单独抬阈值
    bash:
      warn: 100
      hard_limit: 200
    read_file:
      warn: 100
      hard_limit: 200
    grep:
      warn: 60
      hard_limit: 100
    glob:
      warn: 60
      hard_limit: 100
    ls:
      warn: 60
      hard_limit: 100
```

#### 场景 3：短 Q&A、低预算、需要快速兜底

```yaml
loop_detection:
  enabled: true
  warn_threshold: 2
  hard_limit: 4
  window_size: 10
  max_tracked_threads: 100
  tool_freq_warn: 15
  tool_freq_hard_limit: 25
```

#### 场景 4：多用户网关高并发

```yaml
max_tracked_threads: 500   # 默认 100 高并发会频繁 LRU 淘汰
```

### 3.7 调参经验

1. **不要先动 `warn_threshold` / `hard_limit`** —— 3/5 几乎不会误报，先动就是弱化最有效的护栏
2. **误报基本都来自 B 层** —— `tool_freq_*` 全局一刀切，首选用 `tool_freq_overrides` 给具体工具开洞
3. **`hard_limit` 触发后果不可逆**：直接清空 tool_calls 强出文本，本轮工作截断
4. **`window_size` 想象成"健忘程度"**：20 = 中间穿插 20 个不同操作，老的同一调用就被忘掉

---

## 四、影响 Agent 行为的参数地图（Tier 分级）

```
┌─ Tier 1: 直接决定 agent 怎么"思考" ─────────────┐
│  models[*]:                                      │
│    max_tokens, temperature                       │
│    supports_thinking, supports_vision            │
│    when_thinking_enabled                         │
│  summarization                                   │
│  loop_detection                                  │
│  subagents.timeout_seconds / max_turns           │
│  memory.injection_enabled / max_injection_tokens │
│  channels.session.config.recursion_limit  ◀━ 隐藏的杀手锏
└──────────────────────────────────────────────────┘
┌─ Tier 2: 决定 agent 能用什么工具、看到多少结果 ─┐
│  tools[*].max_results                            │
│  tool_search.enabled                             │
│  sandbox.bash_output_max_chars                   │
│  sandbox.read_file_output_max_chars              │
│  sandbox.allow_host_bash                         │
└──────────────────────────────────────────────────┘
┌─ Tier 3: 周边能力 ───────────────────────────────┐
│  title, uploads, safety_finish_reason            │
│  skills.container_path, run_events               │
└──────────────────────────────────────────────────┘
┌─ Tier 4: 默认关闭的高阶护栏 ─────────────────────┐
│  guardrails, circuit_breaker, skill_evolution    │
└──────────────────────────────────────────────────┘
```

### Tier 1：直接决定 agent 怎么思考

#### 1. `models[*]` —— 单模型核心调节

| 参数 | 默认/示例 | 实际影响 |
|---|---|---|
| `max_tokens` | 4096~16384 | 单轮输出上限。给小了 agent 写代码会被截断；给大了一些模型反而变啰嗦 |
| `temperature` | 0.0~1.0 | 0=最确定（适合代码/工具调用），0.7=均衡，1.0=有创意。MiniMax 要求 (0,1]，deepseek 习惯 0.5 |
| `supports_thinking` | true/false | 开启后调用工具前先"想一遍"，**质量明显升高但延迟翻倍** |
| `when_thinking_enabled` | extra_body 配置 | 给底层 API 传思考开关参数，每家厂商写法不一样 |
| `supports_vision` | true/false | false 就不能挂载 `view_image` 工具，上传图片也看不见 |
| `supports_reasoning_effort` | true/false | 允许前端动态调"低/中/高"推理强度 |
| `request_timeout` / `timeout` | 600.0 | 单次 API 调用超时。思考模型可能要 5+ 分钟 |
| `max_retries` | 2 | 网络抖动时重试。**别设 >5**，会和 circuit_breaker 打架 |

**最容易踩的坑**：
- `temperature: 0` 配 `supports_thinking: true` → 思考过程可能完全相同，agent 卡死时跳不出来
- `max_tokens` 给太小（< 2048）→ 工具调用 args 被截断、JSON 解析失败

#### 2. `subagents` —— 子代理工作时长

```yaml
subagents:
  timeout_seconds: 900       # 默认 15 分钟，子任务超时直接 kill
  max_turns: 120             # 子代理最多走 120 步
  agents:
    general-purpose:
      timeout_seconds: 1800  # 复杂研究类调到 30 分钟
      max_turns: 160
    bash:
      timeout_seconds: 300   # bash 子代理 5 分钟够了
      max_turns: 80
```

**影响**：
- `timeout_seconds` 太小 → 复杂研究任务总是被截断
- `max_turns` 太小 → 子代理还没完成就被强终止
- 不设 → 用 lead agent 的 `recursion_limit`（默认 25），通常不够

#### 3. `memory.injection_enabled` + `max_injection_tokens`

```yaml
memory:
  injection_enabled: true         # ← false vs true 差异巨大
  max_injection_tokens: 2000      # 每轮注入记忆的 token 上限
  max_facts: 100                  # 总存量
  fact_confidence_threshold: 0.7  # < 0.7 的事实不存
```

**影响**：
- `injection_enabled: true` → 每轮系统提示词里塞过去对话提炼的"用户偏好/已知事实"，长期记忆
- 代价是每轮多花 2000 token，且如果 memory 抓得不准会污染对话
- 当前 config 设 `false` —— 记忆只存不读，保守做法

#### 4. **`recursion_limit` —— 最被低估的关键参数**

```yaml
channels:
  session:
    config:
      recursion_limit: 100      # ← 默认 LangGraph 是 25！
```

**这是什么**：LangGraph 的"最大图节点访问次数"，相当于 agent 的总步数上限。每次模型响应 + 每个工具调用都算节点访问。

**默认 25 意味着**：复杂任务（"搜索 + 读 5 个文件 + 写代码 + 测试"）经常在中途**直接被 LangGraph 截断**，报错很隐晦（看起来像"agent 突然不说话了"）。

**建议**：
- 单用户/复杂任务：**100~150**
- 仅短问答：**50** 足够
- 长链路 autonomous agent：**200+**

虽然只在 `channels` 段示例里出现，但通过 `client.runs.stream(config={"recursion_limit": ...})` 可以为所有调用设置。

### Tier 2：决定 agent 看到什么

#### 5. `sandbox.*_output_max_chars` —— 工具结果截断

```yaml
sandbox:
  bash_output_max_chars: 20000        # bash 输出 > 20K 字符就截断（中间截）
  read_file_output_max_chars: 50000   # 文件读 > 50K 截头部
  ls_output_max_chars: 20000          # ls 输出 > 20K 截头部
```

**影响**：
- 给小了：agent 经常看不到完整结果，反复重试或猜测
- 给大了：单个工具调用就把上下文窗口占满
- 中间截 vs 头部截：bash 错误可能在结尾，所以中间截；`read_file` 内容前半段最重要，所以头部截

**经验值**：
- 普通用：默认即可
- 大代码库分析：`read_file_output_max_chars: 100000`、`bash_output_max_chars: 40000`
- 短问答：降到一半省 token

#### 6. `tools[*].max_results`

```yaml
- name: web_search
  max_results: 5          # 越大越全，但每条都进入上下文
- name: glob
  max_results: 200        # 文件列表
- name: grep
  max_results: 100        # 搜索匹配
```

**影响**：直接决定 agent 一次能看多少。web_search 5 → 10 质量明显提升，但 token 翻倍。

#### 7. `tool_search.enabled` —— MCP 工具按需加载

```yaml
tool_search:
  enabled: false   # 默认 false
```

**影响**：
- `false`：所有 MCP 工具的 schema 都塞进系统提示词。MCP 多了会爆上下文
- `true`：只列名称，需要时调用 `tool_search` 才加载 schema。节省 5-20K token 但增加一次工具调用

**何时开启**：接了 5+ 个 MCP server，每个都有十几个工具时

#### 8. `sandbox.allow_host_bash` —— 安全 vs 能力

```yaml
sandbox:
  allow_host_bash: false   # 默认 false（安全）
```

**影响**：
- `false`：agent 想跑 bash 必须用 AIO 容器沙箱
- `true`：bash 工具直接在你主机上执行 —— 给 agent 一把电脑的钥匙

当前 config 设的 `true` —— 只在你完全信任 + 单用户本地环境才合适。

### Tier 3：周边能力（影响小但要知道）

| 段 | 参数 | 简述 |
|---|---|---|
| `title` | `max_words: 6`, `max_chars: 60` | 自动生成对话标题的长度限制 |
| `uploads` | `max_files: 10`, `max_file_size: 52428800` | 上传限制（50MB） |
| `uploads` | `auto_convert_documents: false` | PDF/Office 是否自动转 markdown。默认关（安全） |
| `safety_finish_reason` | `enabled: true` | 检测厂商返回的内容过滤/拒绝信号。**默认开就行，关掉会让被截断的不可靠 tool_calls 被错执行** |
| `run_events` | `backend: memory` | 运行事件存哪里。生产用 `db`，否则重启丢失所有 trace |
| `run_events` | `max_trace_content: 10240` | 单个 trace 截断阈值 |

### Tier 4：默认关闭的高阶护栏

#### `circuit_breaker` —— 真正应该开启的失败保护

```yaml
circuit_breaker:
  failure_threshold: 5        # 连续 5 次失败就熔断
  recovery_timeout_sec: 60    # 60 秒后尝试恢复
```

**影响**：模型 API 抖动/宕机时，不开会一直重试到把整轮 token 烧完；开了 5 次失败后直接快速返回错误，60 秒后才再试。

**建议：开**。免费的省钱保险。

#### `guardrails` —— 工具调用授权

```yaml
guardrails:
  enabled: true
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      denied_tools: ["bash", "write_file"]
```

**影响**：每个 tool call 前过一遍授权 provider。**只在多租户或不可信用户场景下需要**。单人本地基本用不上。

#### `skill_evolution` —— 让 agent 自己写 skill

```yaml
skill_evolution:
  enabled: false   # 极度激进，agent 可以写文件到 skills/custom
```

**风险高** —— 本质是让 agent 修改自己的能力。研究用途以外**保持关闭**。

---

## 五、一句话决策清单

按"是否值得动"的优先级：

| 优先级 | 改什么 | 为什么 |
|---|---|---|
| 🔴 高 | `models[*].max_tokens` / `temperature` | 直接决定每轮输出质量 |
| 🔴 高 | `recursion_limit`（通过 channels 或代码） | 默认 25 太小，复杂任务必崩 |
| 🟡 中 | `summarization.*` | 长对话稳定性关键 |
| 🟡 中 | `loop_detection.tool_freq_overrides` | 误报多时给具体工具开洞 |
| 🟡 中 | `subagents.timeout_seconds` / `max_turns` | 用 task 委派时必调 |
| 🟢 低 | `circuit_breaker` | 开了无副作用，避免 API 抖动浪费 |
| 🟢 低 | `sandbox.*_output_max_chars` | 大代码库分析时调高 |
| ⚪ 按需 | `memory.injection_enabled` | 想要长期记忆就开 |
| ⚪ 按需 | `tool_search.enabled` | MCP 工具爆炸时开 |

### 关键提醒

1. **`fraction: 0.8` 类摘要触发器在当前 DeerFlow 配置下用不了**，会启动报错。继续用 `type: tokens`。
2. **`preserve_recent_skill_tokens` 必须远小于 `trigger.tokens`**，否则摘要永远压不下来。
3. **`recursion_limit` 默认 25 是隐形天花板**，复杂 agent 任务请显式调到 100+。
4. **Loop detection 默认值已经很合理**，没遇到具体问题别动 A 套（warn_threshold/hard_limit）。
5. **`allow_host_bash: true` 等于把主机 shell 钥匙交给 agent**，多用户场景必须关。

---

## 附录：源码追溯索引

| 主题 | 源码位置 |
|---|---|
| SummarizationConfig | `backend/packages/harness/deerflow/config/summarization_config.py:21` |
| DeerFlowSummarizationMiddleware | `backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py:98` |
| langchain SummarizationMiddleware（fraction 实现） | `backend/.venv/lib/python3.12/site-packages/langchain/agents/middleware/summarization.py:401` |
| LoopDetectionConfig | `backend/packages/harness/deerflow/config/loop_detection_config.py:24` |
| LoopDetectionMiddleware | `backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py:174` |
| Tool hash key 提取 | `backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py:99` (`_stable_tool_key`) |
| `_get_profile_limits`（fraction 依赖） | `backend/.venv/lib/python3.12/site-packages/langchain/agents/middleware/summarization.py:476` |
| 默认值常量 | `backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py:63-69` |

---

*本文档由 Claude Code 调研生成，调研日期：2026-06-10。*
