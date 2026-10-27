# 第四章：项目结构与模块划分

开始日期：2026-09-15  
本地 DeerFlow 提交：`99367100`  
教材：[deerflow-book 第四章](https://github.com/hawkli-1994/deerflow-book/blob/main/chapters/04-project-structure.md)  
原始内容：[第四章 Markdown](https://raw.githubusercontent.com/hawkli-1994/deerflow-book/main/chapters/04-project-structure.md)  
状态：2026-09-21 项目与算法均已收尾保存。轮换第 2 次个人项目时段完成七个正式工具测试（有提示），已讨论财报证据字段及单位一致性；金融功能尚未实现。算法复习 D06 后完成 D07 首次练习（有提示），修正版10/10通过。下一次项目为第 3 次企业时段，见 [图书查询学习记录](../enterprise-book/progress.md)，随后算法复习 D07、学习 D08；第4次个人时段接续财报证据读取。第四章、多用户实际验证及最终功能验收仍未完成。

## 2026-09-21：个人项目复习起点

- 按长期约定先进行 5～8 分钟项目复习。学习者正确判断 patch 下不会读取真实文件，但将临时替换引用表述为“函数被短暂改写”，对调用断言表述为“调用 runtime 和 path”；已澄清为临时替换使用位置的函数引用，以及检查读取函数恰好调用一次、参数依次为 runtime 和 path。随后对“两次读取、返回值仍为 3”的变式，学习者自行正确判断调用次数断言失败、结果断言通过，并说明原因。该变式通过；尚未独立复写测试，不据此标记完整测试设计已掌握。
- splitlines 边界理解：学习者正确回答无末尾换行、中间空白行、仅一个换行符三个输入分别返回 2、3、1；在给定用例与期望值后，自行新增三个测试。首版结果断言正确，6 passed in 1.58s，但遗漏三个用例的调用次数/参数断言。经提醒后学习者自行补齐，助手读取保存代码，确认 as mock_read 及 with 内的 assert_called_once_with(runtime, path) 位置、参数正确，再运行本机 pytest，得到 6 passed in 1.51s。本步完成（有提示），助手未代写测试；这些测试仍只覆盖模拟读取下的函数行为，不验证真实 Sandbox、运行时注入或用户隔离。之后接续模型可见参数检查和正式测试整理。
- 模型参数理解：学习者正确回答模型只填写 path，但不清楚 runtime 的提供者。助手核对本地 tools/types.py 与 LangGraph ToolNode，讲解 ToolRuntime 的框架注入。随后学习者正确判断直接调用 .func 不会自动注入，并解释这是普通 Python 函数调用。真实注入未在本次重新验证。
- 参数约束测试已完成（有提示）：助手讲解 tool_call_schema.model_json_schema() 返回工具说明字典；学习者不会集合键断言，随后又询问内容比较与对象地址，已讲解 set(字典) 取键、内置容器 == 比较内容与 is 判断同一对象，并提供两条断言。学习者保存 test_count_file_lines_model_parameters，properties 的键集合及 required 列表均断言仅有 path，代码正确。助手运行完整练习文件，最新结果 7 passed in 1.58s；这是元数据检查，不执行工具、模型或真实文件读取。独立复写该测试仍待复习。
- 正式测试整理完成：学习者自行创建 backend/tests/test_count_file_lines.py，复制七个用例并清理 TODO、更新顶部说明；从 backend 目录运行得到 7 passed in 1.66s。助手仅用 Ruff 整理该文件的导入顺序和格式，更新相关文档，并将普通工作区与学习工作区的 pytest 目标切到正式文件，避免重复收集练习副本。按实际 VS Code 配置参数在本机运行，最新为 7 passed in 1.63s；该文件 Ruff 检查及格式检查均通过。尚未实际操作 VS Code 界面，也未运行全后端或 blocking-I/O 套件，不将单文件通过记作整个后端验收通过。
- 财报需求讨论：面对虚构的两年营收数值，学习者自行提出对应年份、营业收入、来源表格和数据位置；助手补充公司、币种与单位，并给出 company/year/metric/value/currency/unit/source 的初步字典示例。对“2024 年 100 万元、2025 年 120 亿元能否直接用原始数字计算增长率”，学习者正确回答不能，需要先统一单位。此处为概念问答通过，尚未编码、换算或验证真实财报，不能记为财报工具已完成。
- 下次个人时段：先复习模型参数断言或财报来源/单位，再用小型文本或 Markdown 教学样例实现可回查出处的数据读取。实现前核对现有文件读取工具和 helper 的复用范围，保留报告期、原始数值与单位、来源文档/表格/位置，再考虑确定性计算；完整证据结构、币种及口径检查尚待设计。
- 这些是财报证据读取功能的前置练习，金融业务功能尚未实现。
- 本日算法已收尾：D06 全负数与更新顺序变式已复习；[D07 合并区间](../interview/day07_notes.md) 学习者自行修正两两合并与越界问题，10/10本地用例通过。时间复杂度漏算排序经纠正，空间 O(n) 及有序输入删排序后的 O(n) 时间回答正确；首次练习完成（有提示），独立复写仍待复习。下一次先企业项目，再复习 D07、进入 D08 和为 K 的子数组。

## 2026-09-20 调整：个人测试留待对应时段

学习者指出原安排未体现企业/个人 60%/40%，已将今天转为企业项目第 1 次时段。下面的计数题仅已提出，尚未作答或验收；下次个人时段从此处继续。

- 学习者主动要求周日学习，只记录本次例外，不自动改变后续休息日或全部日期。
- 已读取现有代码：普通文本、空文本与缺失文件三个测试保留，普通文本用例已有读取次数/参数断言。没有修改学习者实现，也没有重复执行未变化的测试。
- 项目目标：补空白行、末尾换行等计数边界及模型可见参数约束；完成后开始财报证据读取需求。按实际进度推进，正式后端测试整理仍需遵守模块验证规范。
- 当前第一步：根据 splitlines 的计数约定，判断 `"alpha\nbeta"`、`"alpha\n\nbeta\n"`、`"\n"` 应返回多少行，再自行补测试。答案和独立完成情况待记录。
- 算法安排：项目时段之后复习 D05 集合空间与累计循环，再进入 D06；目前尚未开始，不能记为完成。

## 项目规划补充（2026-09-18，D05 学习结束后）

学习者确认没有后端经验，要求一个企业项目与一个个人项目，并确认已有获准参与的内部项目。后续明确：企业为 Hermes＋企业微信连接数据库查询图书数据；个人要求金融方向，分配为 DeerFlow 财报研读与对比助手。已更新 企业与个人项目分配（旧学习计划已删除）；企业本人具体模块与数据库接入方式仍待核对。后端基础改为实作，原日期作为阶段复盘参考。当前工具测试与 D06 算法停点不变，新增规划不代表财报功能已实现或企业项目已上线。

## D05 续学（2026-09-18）

项目停点：学习者已在普通文件测试中给 patch 增加 as mock_read，并在工具调用后使用 assert_called_once_with(runtime, path)，保留 assert result == 3；异常测试也已自行去掉无用的 result 赋值。助手读取代码并在本机运行整个文件，确认 normal、empty、missing 三个测试全部通过（3 passed in 1.53s）。本次工具测试入门练习与运行说明已完成；测试尚在学习目录，其他计数边界、模型参数约束和正式后端测试整理留待下次，不据此宣告工具或整章最终验收完成。

本日算法已收尾：[D05 记录](../interview/day05_notes.md) 保存了从首版 4/8 到修正版 12/12 的验证、嵌套循环累计次数讲解、空间漏算集合的纠正及单元复盘。学习者正确解释了两数之和需要数字到下标的映射、最长连续序列只需查询存在性；完整独立复杂度解释与复写保留为后续任务。

- 异常理解检查记录：学习者对“工具捕获 FileNotFoundError 后返回 0，缺失文件测试是否通过”回答“失败，因为第三个要求接受到异常才能通过”，判断与理由正确。
- assert_called_once_with 已解释：模拟对象记录调用次数和参数，该方法检查已有记录，不会再次读取文件。学习者按提示完成参数断言；当前只标记有提示的实践通过，不记为独立设计完整测试。

- 空文件用例阶段记录：学习者参考首个测试新增 test_count_file_lines_empty()，使用 return_value="" 与 assert result == 0；助手此前核对 2 passed in 1.58s。两个用例沿用相同路径没有问题，因为模拟读取行为由 patch 控制。
- 学习者追问 with 含义，已解释上下文管理、文件关闭示例、patch 的替换/恢复和 pytest.raises 的异常检查，并说明 with 本身不保证吞掉异常。随后学习者提交第三个测试，见当前停点。

- 今日顺序：工具自动化测试与运行说明 → D04 复习 → D05 最长连续序列。按周五安排保留薄弱项复盘，不把未完成内容提前勾选。
- 当前环境：四个 DeerFlow 容器仍在运行，后端容器可使用 pytest 9.0.3。
- 已创建 [工具测试练习](exercises/03_tool_tests/test_file_stats.py)。助手提供导入、模拟读取与调用骨架，学习者先补结果断言。练习位于学习目录，完成后再整理进入正式测试目录；尚未完成或通过测试。
- 骨架加载检查：后端容器运行 pytest --collect-only，成功收集 1 个测试，导入无报错；没有执行测试函数，不能记为测试通过。
- 本步说明：assert 检查结果；patch 在测试期间控制读取函数返回的文本；工具对象的 .func 调用原 Python 函数。本步只验证计数逻辑，不验证真实 Sandbox 读取、框架注入或用户隔离；昨天的真实调用证据继续保留。
- 学习者明确表示 assert、patch、.func 三种写法均不认识，要求逐项详细解释。本次先讲断言的成功/失败行为、with patch 的临时替换与恢复、工具对象保存的原函数及直接调用，再串起测试过程；暂停补断言任务，尚未收到理解反馈，不记为掌握。
- 学习者追问函数对象与临时替换，已用函数名赋值、保存原引用、临时换成替身再恢复的例子说明：patch 改变使用位置的名字所引用的对象，不修改原函数体；with 管理生效与恢复时机。尚未独立验证这部分理解。
- 学习者保存 assert result == 3 后报告运行报错。助手读取当前文件并在后端容器运行 pytest，结果 1 passed in 3.60s；随后在 Windows 本机执行 python learning/deerflow-book/exercises/03_tool_tests/test_file_stats.py，复现第 9 行 ModuleNotFoundError: No module named 'deerflow'。这是本机解释器的包导入问题，不能据此判定断言或计数逻辑有错。未收到学习者原始报错文本，已明确复现环境，并提供容器内 pytest 命令；学习者自行运行结果待反馈。未修改学习者代码，未调用模型或读取真实文件。
- 学习者询问 VS Code 测试功能配置。助手确认本机已安装 Python 扩展、没有 backend Windows 虚拟环境；容器解释器为 /app/backend/.venv/bin/python3。已通过 CLI 安装微软 Dev Containers 扩展，创建 [容器测试工作区](deerflow-tests.code-workspace) 和 [操作说明](exercises/03_tool_tests/README.md)。读取工作区 JSON 并按其中解释器、工作目录和 pytest 参数在容器执行，得到 1 passed in 3.52s。尚未实际连接 VS Code 容器窗口、安装远程 Python 扩展或验收界面按钮，已提供这些步骤。学习者代码保持不变，下一步仍为边界/异常测试。
- 学习者认为连接容器步骤过多，希望像 Java 测试一样直接在项目里运行。助手改为本机方案：使用已安装的 Python 3.12.13 执行 uv sync --locked，创建 backend/.venv 并安装项目依赖及开发工具（安装成功，现有锁文件未修改）；容器的 /app/backend/.venv 是独立 Docker volume。本机直接执行 .\backend\.venv\Scripts\python.exe -m pytest learning/deerflow-book/exercises/03_tool_tests -q --tb=short，结果 1 passed in 5.14s。
- 已在本机 .vscode/settings.json 配置项目虚拟环境、pytest 和练习测试目录，保留原有关闭灰色补全设置；学习测试工作区也改为本机环境，操作说明已重写为本机三步流程。默认续学不再要求连接容器。VS Code 已选解释器可能需手动切换一次，实际界面点击结果待学习者确认。未修改工具和学习者测试逻辑，未新增模型调用。
- 学习者最初未在列表找到解释器；助手确认本机 python.exe 存在、可运行 Python 3.12.13 和 pytest 9.0.3，并说明手动路径选择/刷新列表及选择框自动收起的行为。随后学习者明确反馈“有绿色对钩了，测试也通过了”，VS Code 界面运行通过按用户反馈记录。现解释本机环境安装、项目依赖、VS Code 配置和 pytest 执行流程；尚不据此认定能够独立重建环境或独立编写完整测试。

## D04 续学（2026-09-17）

- 固定顺序不变：先 DeerFlow，再算法。本次项目时段已保存暂停，开始 D03 末尾进位复习，再进入 D04 字母异位词分组；复习回答与新题实现仍待提交。
- 环境事实补记：9 月 16 日已启动 Gateway、Frontend、Nginx、Redis，网页与健康接口通过，`create_chat_model()` 调用 DeepSeek 返回 `OK`；见 [本地启动记录](本地启动记录.md)。9 月 17 日恢复学习时再次检查 `/health`，返回 HTTP 200、`healthy`。这不等于已验收完整 Agent 工具调用。
- 今日项目目标：串起“工具参数来源 → 当前用户/会话对应的 Sandbox → 文件行数统计”的源码与实作，再结合已启动环境追踪一次实际请求。按理解进度推进，不因一个判断题答对就结束整个项目时段。
- 第一题沿用上次停点：调整 `count_file_lines(path, user_id, thread_id)` 的函数签名，通过框架注入的运行上下文取得身份信息；先只写 `def` 那一行。尚未作答，不标记完成。
- 学习者询问在哪写，已创建 [D04 工具练习文件](exercises/02_tool_runtime/main.py)。文件提供导入和待调整的原签名，函数体保留 `NotImplementedError`；当前只修改签名，不运行。后续使用已安装项目依赖的后端环境验证，尚未验收。
- 9 月 16 日补充讨论过：Hermes 与 DeerFlow 的实现区别、按用户划分长期记忆、自定义 Agent 默认管理开关及归属、Codex 接入基础，以及前端开发服务器的实际内存占用。这些讨论不替代工具实作验收。

### D04 签名提交与下一步

- 学习者提交 `def count_file_lines(path: str, runtime:Runtime) -> int:`，签名正确。仅冒号后的空格可按常规格式补齐，不影响本次结果。
- 助手通过后端容器 `runpy.run_path()` 加载练习文件，检查 `tool_call_schema.model_json_schema()`，得到模型可见参数 `['path']`、必填参数 `['path']`。没有执行工具函数体，也没有调用大模型，因此尚不能标记运行时注入或真实工具执行通过。
- 下一步复用 `deerflow.sandbox.tools.read_current_file_content(runtime, path)`：该函数沿既有 Sandbox 初始化和路径解析规则返回原始文本，避免将 `read_file` 工具为展示添加的空文件提示、行号或截断信息算成内容。
- 由学习者自行补导入和函数体：读取文本、使用 `splitlines()` 拆行、返回行数。约定空字符串为 0 行，末尾换行不额外增加一行；正常文件、空文件、无末尾换行等用例随后验证。
- 首版函数体已提交：已补 helper 导入，调用写为 `read_current_file_content(path, runtime)`，随后 `print(text.splitlines())`，同时删掉了函数内的 docstring。助手在后端容器实际加载，得到 `ValueError: Function must have a docstring if description not provided.`；因此行数用例尚未执行。接下来由学习者恢复函数说明、按 helper 的 `(runtime, path)` 顺序传参，并用 `len` 与 `return` 返回整数行数；助手未代写实现。
- 第二版函数体已提交：学习者自行恢复函数 docstring，改为 `read_current_file_content(runtime, path)`，并用 `return len(text.splitlines())` 返回整数。助手重新加载成功，确认模型可见及必填参数仍只有 `path`。
- 函数逻辑验证通过 6/6：普通三行无末尾换行为 3、带末尾换行为 3、空文本为 0、单行为 1、中间含空行为 3、Windows 换行的两行为 2。每例同时检查返回值为 int，并断言 helper 收到 `(runtime, path)`。本次用 Mock 提供原始文本，直接调用工具底层函数；没有读真实 Sandbox 文件，没有验证框架注入，也没有调用大模型。学习者实现保留，助手未代写。
- 工具注册检查已回答：学习者表示“需要在创建 agent 的时候把这个工具传到工具列表中”，理解正确。下一步结合本地源码学习配置加载链：`config.yaml` 的 `tools` → `get_available_tools()` 中的 `resolve_variable(cfg.use, BaseTool)` → 分组与授权等处理 → `create_agent(tools=final_tools)`。源码入口为 `tools/tools.py:86`、`agents/lead_agent/agent.py:1131` 和 `:1182`；配置示例为 `config.example.yaml:1106` 的 `read_file`。
- 配置路径推导已回答：学习者给出 `deerflow.tools.file_stats:count_file_lines`，模块与对象名称对应正确；实际 YAML 使用普通字符串，不包含聊天排版的反引号或转义反斜杠。助手确认 `backend/packages/harness/deerflow/tools/file_stats.py` 尚不存在，不能据此标记模块加载或注册完成。
- 模块保存已完成：学习者将三条 import 和完整工具定义复制到 `backend/packages/harness/deerflow/tools/file_stats.py`，函数说明和逻辑正确，仍带有已完成的教学 TODO 注释。助手在后端容器调用 `resolve_variable("deerflow.tools.file_stats:count_file_lines", BaseTool)` 成功，得到 StructuredTool；检查工具名、模型参数与必填参数通过，并用 Mock 断言加载期间没有执行读取函数。本次是实际模块解析验证，不是完整工具执行验收。
- 根配置已提交：学习者在已有 `tools:` 中正确添加 `count_file_lines`，位于 `config.yaml:1129`。助手在后端容器通过 `get_app_config()` 验证条目唯一、分组与 `use` 正确；调用 `get_available_tools(include_mcp=False, app_config=config)` 找到该工具，模型可见及必填参数仍只有 `path`。进一步确认 `groups=['file:read']` 包含它、`groups=['file:write']` 不包含它。本次省略 MCP 加载，没有调用模型或执行工具；没有输出配置凭据。网页入口 `/health` 返回 healthy。
- 网页实作已提交截图：学习者上传 [三行 sample.txt](exercises/02_tool_runtime/sample.txt) 并请求调用，回复显示结果 3。助手进一步核对日志、归属该用户的 run 状态与实际上传文件：文件 17 字节、3 行，run 状态 success。当前 `run_events.backend=memory`，数据库事件表无该会话记录不等于工具未调用。
- 实际调用证据：通过只读数据库连接和项目的 `build_thread_checkpoint_state_accessor()` 读取该会话保存的消息；工具调用为 `count_file_lines`，参数仅 `{"path": "/mnt/user-data/uploads/sample.txt"}`，对应 ToolMessage 的 content 为 `"3"`、status 为 `success`，两者 tool_call_id 均为 `call_00_ET_4PUIVFLXvhCI4YDYhg8C5360`。会话 `6d7c2ee3-9a64-4170-88a9-3e4cb82edc07`，run `3cec50f1-70b2-479c-8e6d-1cb2664f739b`。核对期间未重跑 Agent、模型或工具。首个正常文件的真实调用通过，异常和多用户案例未做运行验收。
- 虚拟路径理解检查已回答：学习者表示“不会，因为不同的用户对应不同的 runtime，所以读取的文件不同”。方向正确，进一步精确为 helper 依据运行上下文中的用户身份、会话信息定位对应目录，而不是靠 runtime 对象本身的地址区分文件；相同用户、相同会话即使重新创建 runtime，也可以读取同一文件。这是理解问答通过，尚未用第二个账号实际验证隔离。截图中的 0.0 KB 来自上传信息按 KB 保留一位小数；不能据此认定空文件，也不能由文件大小推断行数。
- 新工具接入概括已讲解：在可导入模块中使用 `@tool`、类型标注与函数说明，配置 `name/group/use`，再验证加载与实际调用；仅纯计算工具可不接收 runtime，需要用户/会话/Sandbox 时再注入；注册可用不代表模型每次都调用。
- 文件不存在的网页实作已提交截图并核对：同一会话仅有一次目标调用，path 为 `/mnt/user-data/uploads/d04_missing_file.txt`，tool_call_id 为 `call_00_GpcXYTC5bFdNyKRV3J2H5611`。保存的 ToolMessage 名称为 count_file_lines、status=error，内容包含 FileNotFoundError 和中间件的恢复提示；对应 run `7c589733-798c-45e4-bc76-f2fe8ad9cfa8` 的状态为 success。文件仍不存在。核对使用只读数据库连接和项目会话状态访问入口，未新增模型或工具调用。
- 中间件实际效果已讲解：工具抛普通异常 → ToolErrorHandlingMiddleware 捕获 → 包装为 status=error 的 ToolMessage → 模型读取结果并回复原因。源码 `tool_error_handling_middleware.py:142` 的异步分支负责捕获，`:69` 构造消息；控制流程异常 GraphBubbleUp 会继续抛出。工具调用失败不必导致整个 run 中止，run success 表示运行正常结束，不等于文件统计目标实现。学习者的工具未手动调用 wrap_tool_call，也已获得该层处理。
- 错误语义检查已回答：学习者表示会和“文件本身存在，但是内容为空”混淆，回答正确。保留空文件成功返回 0、缺失文件抛异常并由中间件处理的区别，未修改工具代码。
- 本次项目时段收尾：已自行实现工具并配置，真实网页正常/缺失文件两种调用已核对；学习记录保存后按长期顺序转入算法。下次 DeerFlow 从补自动化回归测试与整理文档继续，保留类型/运行上下文参数约束、计数边界和缺失文件错误语义；多用户实际验证仍待安排，不标记整章或独立二次开发已完成。
- D03 末尾进位复习已回答：学习者用 `400+600` 举例，指出删掉 carry 条件会提前退出并返回 `000`，例子与原因正确。随后 [D04 字母异位词分组](../interview/day04_notes.md) 首次练习已完成（有提示），代码 10 个用例通过，时间 O(n*k)、额外空间 O(n) 回答正确，完整分组键解释与独立复写保留为复习项。本次项目与算法进度均已保存，下次先项目再算法。

## 本次保存与下次起点（2026-09-16）

学习者明确要求“保存进度，开始算法的学习”。本次暂停 DeerFlow，接着学习 D03 字符串相加；长期先 DeerFlow、再算法的顺序保持不变。

下次 DeerFlow 从下面的签名设计题继续，不重做已通过的实例练习：

```python
# 待调整的设计：当前把 user_id 和 thread_id 暴露为模型可填写参数。
@tool
def count_file_lines(path: str, user_id: str, thread_id: str) -> int:
    ...
```

任务：调整函数签名，让工具通过运行上下文取得当前用户与会话信息。只要求学习者先写 `def` 那一行，尚未收到答案。已讲解 `path` 来自模型工具调用，`runtime: Runtime` 由框架注入；不将“讲解过”记为独立掌握。接下来再推进工具实现与环境验证。

本次编码证据：`configured_main.py` 的三个分支由学习者填写，异常消息经提示补充；助手传入 `local`、`container`、`conr` 逐个验证通过。尚未验收学习者自行修改配置、运行全部场景的完整过程。当前教学 JSON 仍为 `conr`，直接运行该入口会按设计报错；之后验证正常读取时再由学习者切换配置。

## 当前续学位置

- [实作 01](exercises/01_sandbox_dispatch/README.md) 的 [configured_main.py](exercises/01_sandbox_dispatch/configured_main.py) 已实现三个选择分支，助手验证 `local`、`container`、`conr` 均符合预期，异常信息经提示修正。学习者正确区分类解析与实例创建，并回答不能调用 `sandbox_id.read_file(path)`：“id 是字符串，要用实例才能运行”。完整调用链独立复述仍待验收。
- 会话缓存检查：`LocalSandboxProvider` 按 `(user_id, thread_id)` 缓存具体实例，`_thread_key` 在 `local_sandbox_provider.py:237`，`acquire` 查找和创建在 `:473`、`:498`。学习者正确回答仅用 thread_id 无法区分不同用户的同名会话；目前是判断题通过，完整原因尚未独立复述。
- 当前续学：`read_file_tool` 的参数来源。`sandbox/tools.py:2394` 中 `path` 等业务参数由模型在工具调用中提供，`runtime: Runtime` 由框架执行工具时注入；`tools/types.py:11` 将 Runtime 定义为 `ToolRuntime[dict[str, Any], ThreadState]`。`_resolve_runtime_thread_id`（`:1488`）先从 runtime.context 取 thread_id，再回退到 runtime.config.configurable。理解检查：新增“统计当前用户文件行数”工具时，能否将 user_id/thread_id 设计成让模型自由填写的参数，应从哪里取得；尚未回答。之后进入工具实现练习。
- 配置补充已讲解：`get_app_config()` 返回 `AppConfig` 对象，读取与解析封装在函数调用链内，`config.sandbox.use` 随后读取对象字段。真实配置为 YAML，教学练习使用 JSON；有效缓存可复用配置对象。这部分尚未验收完整独立复述。
- 中间件已答：执行前日志放在 `handler(request)` 之前；已注册中间件时，新增工具无需手动调用 `wrap_tool_call`。学习者尚未独立复述完整调度原因。
- Skills 已答：任务指导优先改 `SKILL.md`；按需加载节省 token、保留上下文容量并减少干扰。发现与加载完整流程、两个目录的独立解释仍待检查。
- 当前讲解：工具层提供模型可调用的入口，随后通过 Sandbox 接口读文件或执行命令；具体实现可以使用本机或远程环境。`Sandbox` 这个名称不代表所有实现都有容器隔离。
- 先前卡点：曾对替换 Sandbox 后工具名能否保持不变回答“不知道”；已通过实例切换与配置选择练习补充，并解释 `tools[*].use` 与独立的 `sandbox.use`。现在把配置选择实现与当前用户、会话对应的 Sandbox 获取过程接起来，暂不进入其他章节。
- 实作核心通过：学习者回答“因为调用的实例 sandbox 变了”。助手进一步解释形参接收不同实例后的方法调用；`return` / `print` 与 `main()` 入口已讲解，完整独立复述仍待后续。
- 当前已经讨论：Gateway 路由与依赖注入、模型响应筛选、Agent 创建与执行、工具注册与动态发现、Graph/Run/Thread、图的构建规则与运行路径。勾选项仅表示有相应回答证据，阅读过的内容不自动记为掌握。
- 本次按学习者明确要求暂停 DeerFlow，进入 D03 字符串相加；算法起点仍是“从个位还是最高位开始，为什么”的未答问题：[D03 学习记录](../interview/day03_notes.md)。下次项目时段从上面的函数签名题继续，第四章未结束。

## 学习顺序

长期偏好（2026-09-16 确认）：以后每个学习日都先学 DeerFlow，再学算法。收到“继续学习”时优先恢复本文件的当前续学位置，项目时段结束后再进入当天算法题。

长期目标（2026-09-16 明确）：学习后能基于 DeerFlow 做二次开发。后续按 二次开发实战路线（旧学习计划已删除） 将概念问答与学习者自行编码、运行排错、行为测试和独立变化相结合；当前已有的“导入/实例/方法调用”卡点先用短练习补齐。环境启动与独立模型调用已验证，完整 Agent 工具调用尚未验收，第四章也尚未完成，不因计划调整提前勾选。具体业务项目方向待学习者选择。

按教材顺序阅读，每次完成一个小节的定位与理解检查。每个小节可以拆成多个学习时段，仍沿用主学习计划的时间预算与休假规则。

1. 4.1：认识目录，补充本地 App / Harness 的职责与依赖方向。
2. 4.2：逐个认识 Gateway、Agent、Skills、Sandbox，找到本地实现入口。
3. 4.3～4.4：认识前端目录、根命令和模块命令的区别。
4. 4.5：区分配置模板、运行配置、配置 schema 与加载逻辑。
5. 4.6～4.7：根据需求选择修改位置，完成本章自测。

## 版本核对

本次读取的 GitHub 渲染页与原始 Markdown 内容不同。旧页面使用 `backend/src/`；原始 Markdown 的主要目录已更新为 `backend/app/` 和 `backend/packages/harness/deerflow/`。后续以本地检出源码为实现依据，教材用于组织阅读顺序。

教材关于 Gateway 只处理非 Agent 操作的描述不适用于本地默认运行方式：本地 Gateway 同时提供 REST API 和嵌入式 Agent runtime；`/api/langgraph/*` 经 Nginx 改写后也交给 Gateway。

依据：[根 AGENTS.md](../../AGENTS.md)、[后端架构说明](../../backend/AGENTS.md)、[Nginx 配置](../../docker/nginx/nginx.conf)。

## 第 1 小节：目录与职责

| 位置（相对仓库根目录） | 职责 |
| --- | --- |
| `frontend/` | Next.js 前端，展示聊天界面、消息与文件 |
| `backend/app/` | 应用接入：Gateway HTTP API 与 IM 渠道 |
| `backend/packages/harness/deerflow/` | 可复用的 Agent 框架：Agent 编排、运行管理、模型、工具、沙箱、记忆、MCP、技能等 |
| `backend/packages/extension-api/` | Python 扩展与宿主之间的公共契约 |
| `skills/` | 技能说明和配套资源；与 Harness 中处理技能的 Python 代码分开 |
| `docker/` | Compose、Nginx 和可选 Provisioner 的部署配置与实现 |
| `scripts/`、根 `Makefile` | 启动、安装、诊断等工程命令 |
| 根配置模板 | `config.example.yaml` 与 `extensions_config.example.json`，供生成实际运行配置 |

App 与 Harness 是代码分层，不表示必须启动两个独立服务器。默认 Gateway 进程会使用 Harness 中的 Python 模块。

依赖方向：App 可以导入 `deerflow.*`；Harness 不得反向导入 `app.*`。这样，Agent 核心能力可以供 Gateway、终端和进程内 Python 调用等入口复用。

## 本次源码入口

- [根目录与服务拓扑](../../AGENTS.md)
- [后端架构说明](../../backend/AGENTS.md)：搜索 `Harness / App Split`。
- [models.py](../../backend/app/gateway/routers/models.py)：应用层的模型列表 HTTP 路由，第 13 行导入 Harness 的 `AppConfig`。
- [app_config.py](../../backend/packages/harness/deerflow/config/app_config.py)：`AppConfig` 所在模块；本节只确认位置，加载过程留到 4.5。
- [test_harness_boundary.py](../../backend/tests/test_harness_boundary.py)：扫描 Harness 的 Python 导入语句，检查是否依赖 App。本次已阅读，未运行。
- [Nginx 配置](../../docker/nginx/nginx.conf)：`/api/langgraph/` 的转发目标是 Gateway。

当前学习用的真实代码：

```python
# backend/app/gateway/routers/models.py
from deerflow.config.app_config import AppConfig
```

`deerflow` 是安装后的 Python 导入包名；对应源码目录位于 `backend/packages/harness/deerflow/`。导入语句不必包含磁盘上的所有父目录名称。

## 理解检查

- [ ] 能分别说明 `frontend/`、`backend/app/`、Harness 的职责。
- [ ] 能解释为什么 App 可以导入 Harness，而 Harness 不应依赖 App。
- [ ] 能区分根目录 `skills/` 的技能资源与 Harness `skills/` 的实现代码。
- [ ] 能为“增加一个 HTTP 接口”和“调整可复用的 Agent 执行逻辑”选择合适的层。

已讨论的问题：一个供网页调用的“查询任务状态”HTTP 接口，其路由应该放在 App 还是 Harness？如果它需要复用运行状态查询能力，两层如何配合？

学习者回答：路由应放 App。已补充说明：HTTP 接入属于 App，运行状态管理与可复用查询能力可以属于 Harness，两层配合完成请求。

## 4.2.1：模型列表接口

源码：[models.py](../../backend/app/gateway/routers/models.py)。

`APIRouter(prefix="/api")` 与 `@router.get("/models")` 组合得到 `GET /api/models`。学习者已正确回答：只修改处理函数名 `list_models` 不会改变接口路径。

已阅读参数：

```python
config: AppConfig = Depends(get_config)
```

- `config` 是处理函数的参数名。
- `AppConfig` 是参数的类型标注。
- `Depends(get_config)` 声明依赖；在 FastAPI 处理请求时，框架调用依赖函数，并把它的返回值传给 `config`。
- [get_config](../../backend/app/gateway/deps.py) 把获取配置的工作交给 Harness 的 `get_app_config`；配置加载细节留到 4.5。

参考：[FastAPI 依赖注入文档](https://fastapi.tiangolo.com/tutorial/dependencies/)。此处描述的是经 FastAPI 调度的请求，普通 Python 函数调用不会自动解析 `Depends`。

- [x] 能根据路由前缀与相对路径判断完整接口路径。
- [x] 能区分处理函数名与对外接口路径。
- [ ] 能解释 `AppConfig` 类型标注与 `Depends(get_config)` 的不同作用。
- [ ] 能说明依赖函数的返回值怎样成为路由函数的实参。

依赖注入问答记录：学习者询问 `get_config` 与 `get_config()` 的区别，经函数对象和执行结果的讲解后确认理解。显式指定依赖时，`Depends` 接收可调用对象；本例传函数本身，框架在处理请求时调用它。`Depends` 本身会在定义接口时创建依赖声明。相关两项独立复述检查暂不勾选。

标签补充：`tags=["models"]` 用于接口文档分组，不参与 URL 拼接。修改为 `tags=["模型管理"]` 不会改变 `/api/models` 路径。

## 模型列表的处理与响应

仍阅读 [models.py](../../backend/app/gateway/routers/models.py)，关注 `visible_models`、`ModelResponse` 和 `ModelsListResponse`。

1. 从注入的配置对象取得 `config.models`。
2. 根据当前用户和授权配置处理模型可见范围，得到 `visible_models`；错误处理取决于 fail-closed 等配置，后续再深入。
3. 为每个可见模型构造 `ModelResponse`，显式选择名称、显示名和能力标记等公开字段。
4. 构造 `ModelsListResponse`，包含 `models` 和 `token_usage` 两个字段。
5. FastAPI 按 `response_model` 处理响应校验、序列化和文档描述，前端收到 JSON 数据。

`ModelResponse` / `ModelsListResponse` 中的 model 指数据模型；这个接口读取已配置模型的信息，不发起 Agent 对话。

`BaseModel` 来自 Pydantic，构造模型时具有运行时字段校验能力，与仅声明字典结构的 `TypedDict` 不同。参考：[FastAPI 响应模型](https://fastapi.tiangolo.com/tutorial/response-model/)。

- [ ] 能解释 `config.models`、`visible_models` 与返回的 `models` 的关系。
- [ ] 能说明单个 `ModelResponse` 和外层 `ModelsListResponse` 的区别。
- [x] 能解释为什么只选择对外公开的配置字段：学习者指出 `ModelResponse` 只包含前端展示所需的模型信息，API Key 等内部连接信息不应对外展示。

响应设计问题已回答：内部配置与公开响应分开，明确选择允许展示的字段。进一步补充：内部配置增加新字段时，不会因为直接序列化整个配置对象而自动出现在这个接口的响应中。

两种筛选需要区分：`visible_models` 决定当前用户可以看到哪些模型；`ModelResponse` 决定每个返回模型公开哪些字段。字段选择不能替代模型可见范围的授权判断。

已回答的问题：如果配置了 A、B、C 三个模型，用户只允许看到 A，是否可以只构造 `ModelResponse`、省掉模型可见范围筛选？

学习者正确回答：不满足要求，这个用户只能查看 A，只能返回 A 的 `ModelResponse`。

- [x] 能区分模型可见范围与公开字段：隐藏 API Key 并不能代替筛选当前用户有权看到的模型。

## 4.2.2：主 Agent 的组装入口

源码：[lead_agent/agent.py](../../backend/packages/harness/deerflow/agents/lead_agent/agent.py)。

`make_lead_agent(config)` 调用 `assemble_lead_agent(config)`，从组装结果中取出 `.graph` 返回。Gateway 可以直接使用包含图和组装描述信息的 `assemble_lead_agent` 结果。

属性访问补充：学习者询问 `.graph` 的含义。已将表达式拆成 `assembly = assemble_lead_agent(config)`、`graph = assembly.graph`、`return graph` 三步解释；点号读取对象属性，读取图本身不会执行任务。返回值的独立复述检查仍待完成。

继续沿组装函数阅读，可找到来自 `langchain.agents` 的 `create_agent` 调用，主要参数为：

| 参数 | 作用 |
| --- | --- |
| `model` | 提供模型推理能力 |
| `tools` | 提供读取文件、执行命令等可调用工具；实际能力取决于选入的工具 |
| `middleware` | 在模型调用、工具执行等环节加入处理逻辑 |
| `system_prompt` | 设置 Agent 的角色、规则与任务处理要求 |
| `state_schema` | 定义运行过程中共享状态的结构 |

这里先理解“组装出可执行的 Agent 图”。随后调用图的执行接口，才会处理具体任务；组装与执行是两个阶段。参考：[LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents)。

- [ ] 能说明 `make_lead_agent` 返回的是什么。
- [x] 能区分 Agent 组装与具体任务执行：学习者正确回答，调用 `make_lead_agent(config)` 只是创建主 Agent，还没有开始任务。

### 从组装到流式执行

执行代码位于 [runtime/runs/worker.py](../../backend/packages/harness/deerflow/runtime/runs/worker.py)，`run_agent` 是后台执行函数。

- 第 1090 行：调用 `agent_factory`，通过 `_agent_graph` 取得可执行图。
- 第 1195～1198 行：单一输出模式分支先取得 `agent.astream(...)` 返回的异步流，再通过 `async for` 消费它，推进执行并接收输出。多模式分支在第 1225 行开始。
- 第 1288 行：`_stream_once(graph_input, initial_runnable_config)` 把当前任务输入和运行配置交给上述流式执行逻辑。

阅读时先关注三个参数：`input_payload` 是任务输入（普通对话包含 `messages`）；`config=stream_config` 是运行配置，例如关联会话的 `thread_id`；`stream_mode` 决定接收哪些种类的输出，例如模型消息片段或状态快照。

`chunk` 表示一次收到的数据，具体结构取决于输出模式，不一定是一段最终答案文本。实际代码会序列化并发布到 `StreamBridge`，供订阅端消费。参考：[LangGraph 流式执行文档](https://docs.langchain.com/oss/python/langgraph/streaming)。

- [x] 能区分任务输入 `input_payload` 与 Agent 的 `system_prompt`：学习者指出前者是任务输入，后者是事先设定的提示词。
- [ ] 能解释 `async for` 如何逐步接收执行过程中的输出。

进一步说明：`input_payload` 更准确地说是本次执行传入的数据，不必包含全部历史上下文；图还可能恢复已有会话状态。系统提示词的规则通常预先设计，但最终内容可以在组装时动态生成。

### 系统提示词的生成

[agent.py](../../backend/packages/harness/deerflow/agents/lead_agent/agent.py) 第 1168 行调用 `apply_prompt_template(...)`，随后把返回值作为 `system_prompt` 传给 `create_agent`。

实现位于 [prompt.py](../../backend/packages/harness/deerflow/agents/lead_agent/prompt.py) 第 1049 行。例如，`subagent_enabled` 为真时构造子 Agent 使用说明，否则令 `subagent_section` 为空字符串；可用技能等信息也参与提示词生成。因此“预先设计规则”不等于“每次都使用完全相同的提示词字符串”。

已回答的问题：如果只在 `system_prompt` 中写“你可以读取文件”，却没有提供任何能访问文件的工具或接口，Agent 就能实际读取文件吗？

学习者正确回答：不能，读取文件需要对应的工具和接口。

- [x] 能区分提示词中的能力说明与实际提供的执行能力。

### 用 read_file 理解工具

源码：[sandbox/tools.py](../../backend/packages/harness/deerflow/sandbox/tools.py) 第 2394 行。

`@tool("read_file", parse_docstring=True)` 将下方函数封装成 LangChain 工具；对模型公开的工具名为 `read_file`，Python 中定义函数使用的名字为 `read_file_tool`。工具名称、用途说明与参数结构帮助模型选择工具和填写参数，函数实现由后端框架调度执行。参考：[LangChain Tools](https://docs.langchain.com/oss/python/langchain/tools)。

这个工具的业务参数包括 `path`、可选的 `description`、`start_line` 和 `end_line`。`description` 是本次读取操作的界面进度说明，不应与工具本身的用途说明混淆。

读取链路：模型请求 `read_file` 并提供路径 → 框架调度工具 → `_read_file_from_sandbox` 获取沙箱并调用 `sandbox.read_file(...)` → 工具返回内容或错误 → 模型根据结果继续处理任务。`read_file` 读取文本，PDF 等二进制格式另需解析工具。

配置定位：[config.example.yaml](../../config.example.yaml) 第 1106 行通过 `use: deerflow.sandbox.tools:read_file_tool` 引用工具对象；工具收集入口为 [tools/tools.py](../../backend/packages/harness/deerflow/tools/tools.py) 的 `get_available_tools`。主 Agent 还会经过工具筛选和组装，再把最终工具交给 `create_agent`；这些细节后续展开。

- [ ] 能说明模型选择工具与后端执行工具的分工。
- [x] 能区分工具名 `read_file` 与 Python 名字 `read_file_tool`：学习者正确选择模型调用的名字为 `read_file`。

工具注册补充：`def` 定义函数，`@tool` 将其封装成工具对象，再由配置加载和组装将工具交给 Agent。`tools=[read_file_tool]` 传入工具对象，此时不执行读取操作。

### 已创建的 Agent 如何使用新增工具

学习者提问：Agent 是否只能调用工具列表里的工具？已经创建的 Agent 想使用新增工具怎么办？

工具需要先注册或通过动态机制接入，框架才能执行它。创建时的工具列表不一定永久固定，但新增工具需要同时解决模型如何知道它，以及执行端如何调用它。

1. **重新组装图**：把新工具加入工具集合，再调用 `create_agent`。这是普通静态工具列表的直接做法；若正确复用兼容的检查点状态和 `thread_id`，重新组装图不必丢失会话历史。
2. **按需公开已经登记的工具**：DeerFlow 启用 `tool_search` 时，MCP 工具已经包含在执行端的工具集合中，但其完整参数结构可以暂不提供给模型。搜索或路由匹配后，中间件根据状态向模型公开这些工具。这是发现现有目录中的工具，不是向该图即时安装全新工具。
3. **运行中动态接入新工具**：LangChain 支持通过模型调用中间件添加工具定义，再通过工具调用中间件为该工具提供执行实现。只给模型补充工具说明而不提供执行实现是不够的。参考：[动态工具选择与注册](https://docs.langchain.com/oss/python/langchain/tools#dynamic-tool-selection)。

本地实现定位：

- [tool_search.py](../../backend/packages/harness/deerflow/tools/builtins/tool_search.py) 的 `assemble_deferred_tools` 保留候选工具，并按需附加搜索工具；搜索目录由本次组装时的候选工具构成。
- [deferred_tool_filter_middleware.py](../../backend/packages/harness/deerflow/agents/middlewares/deferred_tool_filter_middleware.py) 筛选本次模型请求中的工具定义，也拦截尚未通过发现步骤公开的工具调用。
- [worker.py](../../backend/packages/harness/deerflow/runtime/runs/worker.py) 第 1090 行在每次 `run_agent` 中调用图工厂；新增工具完成配置和加载后，可在后续运行组装的新图中纳入，不能据此认为执行中的旧图自动更新。
- [client.py](../../backend/packages/harness/deerflow/client.py) 第 244 行的 `DeerFlowClient.reset_agent()` 清除客户端的 Agent 缓存，让下一次调用重新组装；这是客户端的方法，不是所有 Agent 图对象都提供的方法。

- [ ] 能区分重新组装、现有工具按需公开、运行时注册新工具。

### Agent 对象、任务执行与会话的生命周期

学习者提问：Agent 的生命周期是什么，创建后是否自动销毁？

需要区分三个对象：可执行的 Agent 图对象、一次任务执行（run）、跨多次执行保存的会话状态（thread）。一次 run 可以包含多次模型调用和工具调用；run 结束不代表会话被删除，也不意味着框架必须立即销毁图对象。

Python 对不再可达的对象进行自动内存管理，具体回收时机不能仅根据 `agent = None` 或 `del agent` 判断；这些操作移除的是引用，其他缓存或执行任务仍可能持有对象。文件、连接和沙箱等资源需要各自的关闭、释放或复用策略。参考：[Python 对象与垃圾回收](https://docs.python.org/3/reference/datamodel.html#objects-values-and-types)。

当前 DeerFlow 的两条使用路径：

| 路径 | Agent 图的处理 |
| --- | --- |
| Gateway 网页运行 | 每次 `run_agent` 调用工厂组装图；终止清理时关闭异步输出流，释放运行期关联引用，并安排循环垃圾回收 |
| 嵌入式 `DeerFlowClient` | 在 `self._agent` 中缓存图，缓存条件一致时复用；`reset_agent()` 清除客户端引用，下一次调用再组装 |

Gateway 的正常终止路径可以概括为：收到任务 → 组装图 → 传入输入与运行配置 → 模型与工具循环 → 本次执行结束 → 清理运行资源与图引用。`worker.py` 第 1656 行的 `agent = None` 是引用清理的一部分，而不是独立的对象销毁 API。

运行后的临时数据也有各自保留期：`worker.py` 为流缓存安排 60 秒后清理；`RunManager.cleanup` 默认 300 秒后移除进程内运行记录。这两个时间不是 Agent 图对象的固定寿命，不会据此删除持久化运行历史。

会话状态由检查点系统按 `thread_id` 管理，可以跨图对象复用；若使用相同存储和兼容图结构，新图可以继续旧会话。内存检查点与数据库检查点的进程重启持久性不同。参考：[LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence)。

源码定位：[worker.py](../../backend/packages/harness/deerflow/runtime/runs/worker.py)（1090、1656、1672 行）、[manager.py](../../backend/packages/harness/deerflow/runtime/runs/manager.py)（1874 行）、[client.py](../../backend/packages/harness/deerflow/client.py)（244、320 行）。

- [ ] 能区分本次任务结束、图对象释放和会话数据删除。

### 图是预先定义还是动态创建

学习者先提出“一个图就是一次任务”的粗略理解，随后询问图是否动态创建、是否只有代码预先写好的几种图。

已解释 Graph 与 Run：图定义可执行逻辑，run 是带着输入执行图的一次过程。同一个图可以执行多次；Gateway 每次运行重新组装图是实现选择，不能把图的概念等同于一次任务。学习者尚未独立复述，不将此项视为已掌握。

分三层理解“动态”：

| 层次 | 当前主 Agent 的情况 |
| --- | --- |
| 构图规则 | DeerFlow 与 LangChain 代码定义组件如何组合，以及模型、工具和中间件如何连接 |
| 图对象 | `assemble_lead_agent` 根据模型、工具、提示词、中间件、状态结构等配置，运行时调用 `create_agent` 组装 |
| 本次执行路线 | 根据用户输入、模型工具调用和执行结果，决定调用什么工具、循环几轮、何时结束 |

主循环可简化为：开始 → 模型 →（需要工具时）工具 → 模型，或模型 → 结束。实际图还包含中间件等逻辑。某次任务先搜索再读取文件，是运行路径的选择，不能据此推断模型临时生成了新的图结构。

源码定位：[agent.py](../../backend/packages/harness/deerflow/agents/lead_agent/agent.py) 第 1182 行；[services.py](../../backend/app/gateway/services.py) 第 605 行表明当前 Gateway 自定义 Agent 也使用同一主 Agent 工厂，通过 `agent_name` 等配置组装不同实例；[langgraph.json](../../backend/langgraph.json) 只登记 `lead_agent` 入口，这是该文件中的入口注册数量，不代表项目所有图对象或辅助图的数量。

LangGraph 不限制开发者只能定义固定几种图，也支持条件路由等动态控制；当前学习重点是“代码定义构图规则，运行时按配置组装，执行时动态选择路径”。参考：[LangGraph 图与路由](https://docs.langchain.com/oss/python/langgraph/graph-api#edges)。

- [ ] 能区分构图规则、运行时创建的图对象和实际执行路线。

后续讨论：组装图由 DeerFlow 与框架代码完成，大模型在执行阶段选择工具和后续行动。学习者提出通过修改图来改进 Agent 系统，已解释节点、连接、条件路由，以及工具、提示词、记忆等不同改进方向。学习者表示“明白了，继续吧”，继续进入中间件，不据此勾选尚未独立复述的检查项。

### 中间件：工具异常处理

本节先理解中间件在 Agent 执行中的位置，详细的中间件链留待后续学习。中间件通过框架定义的钩子，在模型调用、工具调用等环节执行；工具由模型提出调用请求，中间件由框架按照注册的钩子调度。参考：[LangChain 中间件概览](https://docs.langchain.com/oss/python/langchain/middleware/overview)。

真实例子：[tool_error_handling_middleware.py](../../backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py) 的 `ToolErrorHandlingMiddleware`：

- 第 123 行 `wrap_tool_call` 是同步包装钩子，第 142 行 `awrap_tool_call` 是异步版本。
- `request` 携带本次工具调用的信息，包括名称和参数。
- `handler` 是框架传入的后续处理函数；`handler(request)` 继续处理这次调用，正常路径最终执行工具并返回结果。
- 普通 `Exception` 被转换成 `status="error"` 的 `ToolMessage`，使模型能获得失败信息，再决定后续行动；该中间件本身不等于自动修复或自动重试。
- `GraphBubbleUp` 等框架控制流信号会重新抛出，保留暂停/恢复机制。教学简化的普通异常分支不代表生产代码会吞掉所有异常。
- 成功结果还会经过元数据标记与 `normalize_tool_result`，本次先不展开。

组装定位：同文件第 307 行将该中间件加入公共运行链，主 Agent 的 `build_middlewares` 复用该运行链，最终交给 `create_agent` 的 `middleware` 参数。

- [ ] 能解释 `request` 和 `handler` 各自的作用。
- [x] 能判断执行前日志的位置：学习者回答在 `handler(request)` 之前（2026-09-16）。
- [x] 能判断新增工具无需手动调用已注册的中间件：学习者回答“不需要”（2026-09-16）；框架调度原因由助手补充。
- [ ] 能区分模型选择工具与框架调用中间件。

2026-09-16 续学：学习者正确回答执行前日志放在 `handler(request)` 之前。接着沿源码定位注册过程：`tool_error_handling_middleware.py:307` 创建实例并加入 `tail`；公共构建函数返回合并后的列表；`lead_agent/agent.py:521` 取得公共运行中间件，最终在第 1185 行经 schema 规范化后传给 `create_agent` 的 `middleware` 参数。模型提出工具调用请求后，由框架执行已注册的钩子；同步版本是 `wrap_tool_call`，异步版本是 `awrap_tool_call`。本节暂不展开 schema 规范化与整个中间件链。

已回答的问题：同一个 Agent 已注册工具异常处理中间件，新增工具加入其 `tools` 后，还需要在工具函数内手动调用 `wrap_tool_call` 吗？学习者回答“不需要”，判断正确。助手补充：工具通过该 Agent 的执行路径运行时，由框架调用已注册的同步或异步钩子；直接在普通 Python 代码里调用工具实现，不会因此自动经过 Agent 的中间件。

2026-09-16 追问：`tail.append(ToolErrorHandlingMiddleware(...))` 如何传到 `create_agent`？已核对完整数据传递路径：

1. `_build_runtime_middlewares` 中 `tail` 是局部列表；第 307 行追加中间件实例，第 309 行用 `[*outer_wrappers, *thread_hooks, *tail]` 展开各列表的元素并合并，第 315 行返回合并列表。
2. `build_lead_runtime_middlewares` 在第 328 行 `return _build_runtime_middlewares(...)`，把内部函数的返回值继续返回。
3. `lead_agent/agent.py` 的 `build_middlewares` 在第 521 行接收该列表，追加主 Agent 中间件后，第 712 / 718 行经 `compose_with_extensions(...)` 处理并返回。
4. `_assemble_lead_agent` 的默认分支在第 1156 行 `middlewares = build_middlewares(...)` 接收最终列表，第 1185 行将 `normalize_middleware_state_schemas(middlewares, mode)` 的返回列表交给 `create_agent` 的 `middleware` 参数。

要点：各函数通过返回值与参数传递数据，不依赖局部变量名字相同。`*tail` 会展开列表元素，不会把整个 `tail` 作为一个嵌套元素加入。规范化函数位于 `thread_state.py:448`，full 模式返回列表副本，delta 模式可能浅复制实例并调整状态 schema，不能笼统说从头到尾始终是同一个列表或同一个实例。本节只解释数据传递，暂不深入状态 schema。

### 构图源码定位补充（2026-09-15）

算法首次练习完成后，学习者额外询问“构建图的代码在哪”。本次只补充代码导航，明天的正式续学位置仍是上面的中间件理解检查。

- DeerFlow 入口：`lead_agent/agent.py` 的 `make_lead_agent`（757 行）→ `assemble_lead_agent`（762 行）→ `_assemble_lead_agent`（877 行）。
- 默认主 Agent 组装：同文件第 1182 行调用从 `langchain.agents` 导入的 `create_agent`；bootstrap 分支另有一次调用。
- 节点和边的实际构造：LangChain 的 `langchain/agents/factory.py` 内 `create_agent`，包含 `StateGraph(...)`、模型/工具/中间件节点的 `graph.add_node(...)`、普通与条件边的连接，以及最终 `graph.compile(...)`。
- 项目 [backend/uv.lock](../../backend/uv.lock) 锁定 `langchain==1.3.14`。已核对该版本的 [factory.py 源码](https://github.com/langchain-ai/langchain/blob/langchain%3D%3D1.3.14/libs/langchain_v1/langchain/agents/factory.py) 与 [原始文件](https://raw.githubusercontent.com/langchain-ai/langchain/refs/tags/langchain%3D%3D1.3.14/libs/langchain_v1/langchain/agents/factory.py)。浏览工具的文本行号不一定等于原始源码行号，在线导航优先搜索上述函数调用。
- 本次在仓库和 backend 常见 `.venv/Lib/site-packages` 位置及当前终端 Python 中未找到 LangChain 安装；没有安装依赖或启动服务。若 VS Code 选择的环境已装依赖，可对 `create_agent` 按 F12 跳入框架实现。

### Agent、工具、中间件的区别与联系（2026-09-16 追问）

学习者主动询问三者的区别与联系。Agent 将模型、工具、状态与中间件组织成可运行的任务流程；模型通常判断下一步并提出工具调用，框架负责实际调度。工具是执行具体操作的可调用接口，如 `read_file`、`bash`。中间件是在模型或工具调用等执行环节运行的处理逻辑，如日志、参数检查、错误处理，也可改写或中止处理。

本地联系：`create_agent(model=..., tools=..., middleware=...)` 将这些组件组装进图；组装时注册组件，图运行时再调度它们。中间件作为中间件注册时由框架执行，不需要模型像选择工具一样选择它。

例子：用户要求读文件并总结 → 模型提出 `read_file` 请求 → 框架通过已注册的工具调用中间件处理请求 → 工具读取文件 → 中间件处理返回结果或普通异常 → 模型根据工具消息继续回答。这里仅展示工具调用环节，中间件也可作用于模型调用等其他环节。直接在普通 Python 代码中调用工具实现不会自动经过 Agent 的中间件。

本次为讲解记录；学习者表示“明白了，下一步吧”，继续 Skills 模块，未据此新增独立理解检查通过项。

## 4.2.3：Skills 模块（2026-09-16 开始学习）

本节先认识技能包和代码所在目录，再追踪发现与读取流程。仅阅读仓库的技能文件作为教材示例，不执行其中的数据分析流程。

| 对象 | 作用 | 本地例子 |
| --- | --- | --- |
| 工具 | 执行具体操作，如读取文件、运行命令 | `read_file`、`bash` |
| 技能包 | 提供任务说明、处理步骤，并可附带脚本、模板等资源 | `skills/public/data-analysis/` |
| 技能管理代码 | 解析、发现、安装和管理技能包 | `backend/packages/harness/deerflow/skills/` |

示例：[data-analysis/SKILL.md](../../skills/public/data-analysis/SKILL.md) 顶部 YAML 元数据包含 `name` 和 `description`，正文说明确认需求、检查文件结构、执行分析等步骤，并引用同目录 `scripts/analyze.py`。脚本仍需通过 `bash` 等工具执行，读取 Markdown 不会自动执行脚本。

两个目录要区分：根目录 `skills/public/` 是公共技能包；Harness 内的 `deerflow/skills/` 是管理这些技能包的 Python 代码。教材此节列出的 `loader.py`、`manager.py` 在当前本地版本不存在，后续按本地 `storage/`、`parser.py`、`installer.py` 等入口追踪，不照抄旧文件名。

源码入口（已介绍作用，尚未逐行教学）：

- `skills/parser.py:190` 的 `parse_skill_file`。
- `skills/storage/local_skill_storage.py:76` 的 `_iter_skill_files`，以及 `storage/skill_storage.py` 中的加载逻辑。
- `agents/lead_agent/prompt.py:866` 的 `get_skills_prompt_section`；默认公开元数据并按需读取正文，延迟发现模式先给名称索引，显式 slash 激活另有正文注入路径。后续再展开这些差异。

理解检查：给数据分析增加“先检查缺失值”的操作指导，应优先改技能的 `SKILL.md`，还是 `read_file` 工具代码？学习者回答“先改 skill.md”，正确。此处讨论操作指导；脚本能力本身若需要改变，仍需修改相应实现。

- [x] 能判断任务操作指导应修改技能说明，而非通用文件读取工具。
- [ ] 能区分技能包目录与技能管理代码目录。
- [ ] 能解释技能发现与按需读取的过程。

### 默认模式下的发现与按需读取

1. 后端代码完成发现：`SkillStorage.load_skills()` 遍历技能文件，调用 `parse_skill_file()`，解析名称、描述、路径等信息，并合并启用状态。`Skill` 对象记录元数据和文件路径。
2. 默认简介模式中，`get_skills_prompt_section()` 取得可用技能；`_render_available_skill()` 生成包含 `<name>`、`<description>`、`<location>` 的条目，组成 `<available_skills>`，随后由 `apply_prompt_template()` 放入系统提示词。
3. 模型依据任务和技能简介判断相关性，按系统提示词的指引调用 `read_file` 读取相关 `SKILL.md`；框架实际执行读取，正文通过工具结果进入模型上下文，再指导后续操作。资料中的脚本不会因读取说明自动执行。

这里的渐进加载描述模型获得详细内容的方式。后端解析元数据时已经读取了文件，不能说此前完全没有发生磁盘读取。显式 `/skill-name` 激活会由运行时注入正文；`skills.deferred_discovery` 模式则先给名称索引、再用 `describe_skill` 取得详情，这两条路径先不展开。

已回答的理解检查：如果有 100 个技能，任务只需要其中一个，先给简介再按需读取有什么好处？学习者回答“能节省时间和 token，也能节约模型的上下文和注意力”。token、上下文容量与减少干扰的方向正确；助手补充：总耗时还取决于额外的工具读取等步骤，不保证每次更快。

- [x] 能说明按需加载减少无关 token、上下文占用和信息干扰。

## 4.2.4：Sandbox 模块（2026-09-16 开始学习）

Sandbox 提供文件访问、命令执行等环境能力的统一接口。具体实现可以是本机，也可以连接容器等远程环境；不能因名字含有“沙箱”就认为所有实现都有容器级隔离。工具层对模型暴露调用入口，Sandbox 实现负责在具体环境中完成操作。

`read_file` 调用链：`read_file_tool` → 全文读取时的 `read_current_file_content` → `_read_file_from_sandbox` → `sandbox.read_file(...)`。按行读取分支直接进入 `_read_file_from_sandbox`；异步工具包装在异步初始化后复用同步工具实现。

主要源码：

- `sandbox/tools.py:2366`：`_read_file_from_sandbox` 先 `ensure_sandbox_initialized(runtime)` 获取实例，准备线程目录，本地模式转换路径，随后调用 `sandbox.read_file(path)` 或带行号的版本。
- `sandbox/sandbox.py:132`：抽象 `Sandbox.read_file` 定义读取接口。
- `sandbox/local/local_sandbox.py:784`：`LocalSandbox.read_file` 解析路径后，使用 `open(resolved_path, encoding="utf-8")` 从本地读取。
- `community/aio_sandbox/aio_sandbox.py:497`：已读取远程实现，对比其 `self._client.file.read_file(file=path, **kwargs)` 调用与本地实现的 `open(...)`。

理解检查：从本地 Sandbox 切换到容器实现后，模型调用的工具还能保持 `read_file` 吗？学习者回答“不知道”。助手解释：工具名称由工具注册定义；工具内部取得具体 Sandbox 实例，并调用该对象的 `read_file` 方法。本地实例执行本地读取实现，AIO 实例通过客户端调用沙箱服务。两者遵循统一方法接口，因此工具名称可以保持；选择对象由后端配置与初始化逻辑完成，Python 不会仅凭方法名自动选择执行环境。路径与配置仍须匹配实际环境。

当前小问题：如果 `sandbox` 保存的是 `LocalSandbox` 实例，执行 `sandbox.read_file(path)` 会调用哪个类里的方法？尚未回答。本次降低问题跨度，先确认实例与方法调用关系，再继续接口抽象。

追加追问：这些 Sandbox 类是通过导包使用的吗，具体实现是否已经写好？已核对：

- 都有现成的 Python 源码；`sandbox/sandbox.py:44` 的 `Sandbox` 是抽象父类，定义接口；`sandbox/local/local_sandbox.py:95` 的 `LocalSandbox` 继承它，读取实现位于第 784 行；`community/aio_sandbox/aio_sandbox.py:47` 的 `AioSandbox` 提供远程服务适配实现。
- `sandbox/local/local_sandbox_provider.py:7` 通过普通 `from ... import LocalSandbox, PathMapping` 导入类，第 500 行通过 `LocalSandbox(...)` 创建具体对象。导入类、创建实例、调用实例方法是不同步骤。
- `get_sandbox_provider()` 位于 `sandbox/sandbox_provider.py:158`：读取配置，通过 `resolve_class(config.sandbox.use, SandboxProvider)` 动态定位 Provider 类，再用 `cls(**kwargs)` 创建 Provider。模板 `config.example.yaml:1327` 的 `sandbox.use` 指向 `deerflow.sandbox.local:LocalSandboxProvider`；这是配置模板示例，不代表已验证用户运行中的实际配置。
- Provider 创建或复用 Sandbox；`ensure_sandbox_initialized` 获取实例后，工具调用其现成的方法。`Sandbox` 抽象父类本身不能当成完整实现直接实例化。

当前学习重点仍是导入类与实例化的区别；上面的实例方法小问题尚未收到回答，不新增理解通过标记。

追加追问：配置工具时是否要分别指定运行在本地还是沙箱？当前代码将两层配置分开：

- `tools[*].use` 指向工具实现，例如 `deerflow.sandbox.tools:read_file_tool`；`name`、`group` 分别是配置名称与分组。通用 `ToolConfig` 没有统一的逐工具执行环境字段。模型绑定采用工具对象自身的 `.name`，配置名称与其不一致时加载器会告警。
- 独立 `sandbox.use` 选择 Sandbox Provider，例如模板中的 `deerflow.sandbox.local:LocalSandboxProvider`，或 AIO 示例中的 `deerflow.community.aio_sandbox:AioSandboxProvider`。
- 通过 Sandbox 接口实现的工具共用这套 Provider 配置，不必给 `read_file`、`write_file` 等逐个指定环境。该配置不会把所有 Python 工具自动搬入容器：工具的 Python 封装通常仍在后端进程中运行，只有委托给 Sandbox 的操作在所选环境执行。自定义工具直接 `open(...)` 时仍访问后端进程所在文件系统。
- 依据：`config.example.yaml:1106` 的工具项、`:1327` 的本地 Provider、`:1368` 的 AIO 示例；`config/tool_config.py:11` 与 `tools/tools.py:93`；配置指南明确 Sandbox 配置属于需要重启后端的项目。

本次仅解释配置与调用关系，未更改运行配置；不将未回答的理解检查标为通过。

2026-09-16 实作开始：学习者要求按二次开发路线开始。已准备 [实作 01](exercises/01_sandbox_dispatch/README.md)，两个普通 Python 教学类用文字模拟本地和容器读取；学习者填写导入、实例创建和调用。第一阶段期望输出“本地实现：读取 report.txt”，通过后再换实例，观察上层函数不变而执行的方法随实例变化。当前只有骨架，未收到学习者实现，不记为实作通过或真实 Sandbox 验证。

首次提交更新：学习者已经正确填写三个步骤中的导入、实例创建和函数调用，遗漏打印返回值。助手阅读代码后运行，退出码 0、无输出；已解释 `return` 将值交给调用方，`print` 才会显示到终端。学习者自行补充打印，修正尚待验证。原始骨架状态保留在上一段作为历史记录。

修正验证更新：学习者已在 `main()` 中保存并打印返回值，助手阅读并执行代码后确认输出“本地实现：读取 report.txt”。现进入第二步，由学习者修改导入与创建实例的类，切换到 `ContainerSandboxDemo` 并保留上层调用。方法调用原因尚待独立解释，不将整个实作记为完成。

第二步验证更新：学习者分别创建两种实例，传入同一个 `read_with_tool`，当前打印容器教学类结果；助手运行输出“容器实现：读取 report02.txt”，与其输入一致。学习者正确回答输出变化因实例不同，前两步核心实作完成。助手曾提前转回算法，学习者指出内容过少，现继续配置选择与真实 Provider 调用链。新增骨架复用原调用函数，学习者填写实例选择与无效配置报错；尚未提交实现。真实容器、项目环境启动与完整第四章均未验收。

- [x] 在教学代码中保持上层函数不变，传入不同实例并观察对应方法的结果。
- [x] 指出实例不同是结果变化的原因；较完整的方法调用解释由助手补充。

- [ ] 能区分工具调用入口与 Sandbox 执行实现。
- [ ] 能解释统一接口为何支持替换底层环境。
