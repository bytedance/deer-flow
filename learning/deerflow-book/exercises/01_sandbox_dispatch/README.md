# 实作 01：导入类、创建实例与方法调用

开始日期：2026-09-16  
对应进度：[第四章 4.2.4 Sandbox](../../ch04_notes.md)  
预计用时：10～15 分钟，纳入今天的 DeerFlow 时段。

## 要弄清的问题

`sandbox.read_file(path)` 究竟调用哪个类的方法，取决于变量 `sandbox` 保存的实例。通过创建不同实例，观察上层调用代码保持不变时返回结果如何变化。

本练习使用普通 Python 类和函数，教学类通过返回文字模拟读取，运行只需要 Python。真实 DeerFlow 的环境创建、路径映射和工具注册不在这次短练习中实现。

## 文件

- [sandbox_examples.py](sandbox_examples.py)：助手提供两个已经实现的教学类，先阅读它们的 `read_file` 方法。
- [main.py](main.py)：学习者填写导入、实例创建和调用代码。`read_with_tool` 已提供，后续替换具体实例时保留这个函数。

## 第一步：运行本地版本

完成 `main.py` 中三个 TODO：

1. 从 `sandbox_examples` 模块导入 `LocalSandboxDemo` 类。
2. 创建 `LocalSandboxDemo` 实例，保存到 `sandbox` 变量。
3. 将该实例和字符串 `"report.txt"` 传给 `read_with_tool`，打印返回值。

填写完成后删除 `NotImplementedError` 占位语句。在仓库根目录运行：

```powershell
python learning/deerflow-book/exercises/01_sandbox_dispatch/main.py
```

期望输出：

```text
本地实现：读取 report.txt
```

首次实作的核心目标已完成：学习者自行填写导入、实例创建和调用，按提示补上 `print` 并整理成 `main()`；本地与容器教学类的输出均已分别核对。学习者能指出输出变化源于传入的实例不同，完整概念复述留待后续。

## 第二步：替换具体实例（已完成）

将使用的类换成 `ContainerSandboxDemo`，调整导入与实例创建，保留 `read_with_tool` 函数及其调用、打印流程。运行后期望输出：

```text
容器实现：读取 report.txt
```

这里仍然只是教学类返回的模拟文字。由学习者自行修改，再解释为何上层函数没变，输出却发生变化。

## 进度

- [x] 助手提供两个教学类与调用函数、学习者待填骨架。
- [x] 学习者完成导入、实例创建和调用。
- [x] 将函数返回值打印到终端：按助手提示补充。
- [x] 学习者确认本地版本可运行；助手复核输出为“本地实现：读取 report.txt”。
- [x] 向同一个上层函数传入两种具体实例，并核对输出。
- [x] 能指出输出变化的原因：传入的实例不同。
- [ ] 独立解释导入类、创建实例、调用方法分别发生了什么。

此练习的成功只说明短 Python 示例通过，不代表 DeerFlow 已启动或真实容器已经接入。

## 首次运行记录（2026-09-16）

学习者已正确写出 `from sandbox_examples import LocalSandboxDemo`、`sandbox = LocalSandboxDemo()`，并调用 `read_with_tool(sandbox=sandbox, path="report.txt")`。学习者反馈没有输出。

助手先阅读两个 Python 文件，再执行 README 中的命令：退出码为 0，标准输出为空。原因是方法和上层函数都使用 `return` 返回字符串，入口调用后没有接收并打印这个值。已说明 `return` 与 `print` 的区别，由学习者补充打印；助手未修改练习实现。修正后的输出尚待验证。

## 修正后验证（2026-09-16）

学习者将入口整理为 `main()`，保存调用结果后执行 `print(result)`，并由 `if __name__ == "__main__": main()` 调用。助手先阅读代码再运行；退出码为 0。工具通道的默认编码使首次中文输出显示异常，因此用 `python -X utf8 learning/deerflow-book/exercises/01_sandbox_dispatch/main.py` 核对，输出确认为“本地实现：读取 report.txt”。不需要因此修改解法。未执行任何真实容器操作。

当前仅本地版本通过，第二步与独立解释尚未完成；助手未替学习者修改两个 Python 文件。

## 第二步验证（2026-09-16）

学习者保留了两个实例：`sandbox_local = LocalSandboxDemo()`、`sandbox_con = ContainerSandboxDemo()`，分别传给同一个 `read_with_tool`；本地参数为 `report.txt`，容器教学类参数为 `report02.txt`，最后打印 `result_con`。助手先读代码再运行，退出码为 0，输出“容器实现：读取 report02.txt”。文件名与第一阶段不同是输入参数变化，不是错误。当前只打印容器教学类结果，本地结果保存在变量中；本地输出此前已验证。

对输出变化原因，学习者回答“因为调用的实例 sandbox 变了”，方向正确。助手补充：上层函数的形参 `sandbox` 在两次调用时接收不同实例，因而执行相应类的 `read_file`。本次核心实作完成，完成方式为自行编码、打印问题经提示修正；未验收真实容器，也未将全部 Python 概念标为独立掌握。

学习安排更新：学习者指出只完成这段热身就结束当天 DeerFlow 内容过少。2026-09-16 继续下面的配置选择练习与真实 Provider 调用链，算法仍排在 DeerFlow 之后。

## 第三步：按配置选择实例（待学习者实现）

目标：切换环境时，只改配置；创建实例的函数根据配置选择类，上层工具调用保持不变。

- [sandbox_config.json](sandbox_config.json)：教学配置，`sandbox.provider` 先设为 `local`，文件路径为 `report.txt`。
- [configured_main.py](configured_main.py)：配置读取、上层调用与打印已提供，只需自己实现 `create_sandbox`。此前的 `main.py` 保留原样。

实现三个分支：

| 输入名称 | 要返回或执行的内容 |
| --- | --- |
| `local` | 返回一个 `LocalSandboxDemo` 实例 |
| `container` | 返回一个 `ContainerSandboxDemo` 实例 |
| 其他名称 | 抛出 `ValueError`，错误信息包含该名称 |

可以使用 `if` / `elif` / `else`。返回的是实例；注意类名后是否有 `()`。抛出异常的写法例如 `raise ValueError("配置名称不受支持")`，本练习还需要把收到的名称放入错误信息。

在 VS Code 打开 `configured_main.py` 后点击运行。也可以从仓库根目录运行：

```powershell
python learning/deerflow-book/exercises/01_sandbox_dispatch/configured_main.py
```

分别修改 JSON 的 `provider` 值，保存后重新运行：

| 配置值 | 预期行为 |
| --- | --- |
| `local` | 显示 `LocalSandboxDemo`，然后“本地实现：读取 report.txt” |
| `container` | 显示 `ContainerSandboxDemo`，然后“容器实现：读取 report.txt” |
| `unknown` | 抛出包含 `unknown` 的 `ValueError`，不执行读取 |

验证后将配置恢复为 `local`。未填写 TODO 时抛出 `NotImplementedError` 是骨架的预期行为，不是环境故障。

`from main import read_with_tool` 复用你之前的函数。被导入文件中的 `if __name__ == "__main__"` 条件此时不成立，所以不会顺带执行之前的演示。配置路径以当前脚本所在目录为准，不受运行按钮使用哪个工作目录影响。

### 对应真实 DeerFlow

本例的 `create_sandbox` 直接返回教学 Sandbox 实例；真实 DeerFlow 另有管理 Sandbox 的 **Provider**。教学 JSON 的字段不是 DeerFlow 的正式配置格式。

真实配置与调用链（相对仓库根目录）：

1. `config.example.yaml:1327`：`sandbox.use` 指定 Provider 的类路径，例如 `deerflow.sandbox.local:LocalSandboxProvider`。
2. `backend/packages/harness/deerflow/sandbox/sandbox_provider.py:158`：`get_sandbox_provider()` 取得已缓存的 Provider；首次初始化时，`resolve_class(config.sandbox.use, SandboxProvider)` 找到类，`cls(**kwargs)` 创建实例。
3. `backend/packages/harness/deerflow/sandbox/tools.py:1558`：需要获取 Sandbox 时，通过 Provider 或租约管理器取得 **sandbox_id**，随后 `provider.get(sandbox_id)` 取得 **Sandbox 实例**。这里的 ID 和实例是不同的返回值。
4. 同文件 `:2366`：读取工具获取 Sandbox 后调用 `sandbox.read_file(path)`，进入具体实现。

Provider 负责获取和管理执行环境；Sandbox 实例提供具体的读取、写入、执行方法。先理解这个主流程，缓存、路径映射和资源租约留待逐步阅读。真实 Provider 有缓存，不能把教学脚本每次重新运行读取配置的效果，当成运行中 DeerFlow 自动切换环境的保证。

### 本阶段验收

- [x] 学习者完成三个分支，正常配置返回实例；异常信息按提示补充。
- [ ] 仅修改配置并重新运行，分别得到两种预期输出。
- [ ] 无效配置报错，能解释为什么不能静默使用本地实现。
- [ ] 在真实源码中定位 Provider 的选择与创建。
- [x] 能指出 Sandbox ID 是字符串，读取方法应在 Sandbox 实例上调用。
- [ ] 能区分 Provider、Sandbox ID 和 Sandbox 实例，并串起一次读取调用。

当前状态（2026-09-16）：学习者完成 `create_sandbox`，两个正常分支返回对应实例，异常分支最初为 `raise ValueError`，按提示改为包含 `provider_name` 的错误信息。助手阅读代码后，分别传入 `local`、`container`、`conr` 运行，得到本地读取、容器读取和包含 `conr` 的 `ValueError`。助手未修改学习者的 Python 实现或配置；JSON 当前仍为 `conr`。这是助手对三个分支的验证，尚不等于学习者已经独立完成“修改配置并运行”的全部检查，也未收到无效配置不应回退本地的独立解释。

源码理解更新：学习者正确回答“第二行只是加载了 provider 的类，第三行才创建实例”，能区分 `resolve_class` 和 `cls(**kwargs)`。已解释 `get_app_config()` 返回配置对象，以及 YAML 配置与教学 JSON 的区别。随后对 `sandbox_id` 能否直接调用 `read_file`，学习者正确回答“不能，id 是字符串，要用实例才能运行”。现在继续 `LocalSandboxProvider` 按用户与会话缓存 Sandbox 的机制，详细停点见第四章记录；完整调用链独立复述待验收。

后续判断：学习者正确回答仅用 thread_id 不能区分不同用户的同名会话，尚未独立展开原因。当前进入工具业务参数与框架注入 runtime 的区别，准备将 Sandbox 获取过程用于新增工具，详见第四章当前续学位置。
