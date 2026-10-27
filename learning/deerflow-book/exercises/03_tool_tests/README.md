# D05 工具自动化测试

本目录保留学习者的练习副本；后续维护的正式文件为 [test_count_file_lines.py](../../../../backend/tests/test_count_file_lines.py)。测试使用模拟读取检查 `count_file_lines` 的函数逻辑，并检查模型可见参数。测试过程不调用大模型；真实 Sandbox 读取、运行上下文注入和用户隔离需要另外验证。

## 在 VS Code 中点击运行

默认在 Windows 本机运行。项目的 Python 虚拟环境位于 `backend/.venv`，`.vscode/settings.json` 已启用 pytest 并指定正式测试文件。也可以打开 [测试工作区](../../deerflow-tests.code-workspace)，使用相同的本机配置。

1. 在普通本机 VS Code 窗口中打开 `F:\harness-learn\deer-flow` 项目。
2. 按 `Ctrl+Shift+P`，执行 `Python: Select Interpreter`，选择 `backend/.venv`。如果列表没有它，选择输入解释器路径并粘贴 `F:\harness-learn\deer-flow\backend\.venv\Scripts\python.exe`。选择一次即可；已手动选择过解释器时，仅修改默认路径不会自动切换。
3. 保存测试文件，在左侧烧杯面板或测试函数左侧点击运行按钮。若列表为空，执行 `Test: Refresh Tests`；失败时查看 Python 测试输出中的报错。

当前 VS Code 只收集 `backend/tests/test_count_file_lines.py` 中的七个测试，避免与练习副本重复；保存后如面板仍显示旧路径，可点击刷新测试。本机运行这些模拟读取测试不依赖 Docker 服务。后端 `make test` 则会随其他后端用例一起收集该文件。

首次安装或重建本机环境时，在 `backend` 目录执行：

```powershell
uv sync --locked --python 3.12
```

这会按照项目现有锁文件安装依赖和开发工具。以后修改自己的 Python 代码通常不用重新安装依赖。

## 终端运行

Windows 本机终端，当前目录为项目根目录：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_count_file_lines.py -q
```

已有 Docker 环境也可以作为备用运行方式：

```powershell
docker exec -w /app/project deer-flow-gateway /app/backend/.venv/bin/python3 -m pytest backend/tests/test_count_file_lines.py -q
```

测试由 pytest 发现并执行，不需要在练习文件中添加 main。普通“运行 Python 文件”按钮不会自动调用其中的测试函数。

## 当前验证范围

2026-09-21：学习者完成六个文件行为测试与一个模型可见参数测试，随后自行复制到正式目录，清理 TODO 并更新文件说明。正式文件首次在后端目录运行得到 `7 passed in 1.66s`。助手用 Ruff 整理该文件的导入顺序、空格与空行，并将 VS Code 的测试目标切换到正式文件；练习副本保留。缺失文件用例检查 FileNotFoundError 继续抛出，模型参数用例检查 properties 和 required 均仅有 path。以上均为有提示的练习；这些单元测试尚未验证真实文件读取、框架注入和中间件，也不代表完整后端测试套件通过。

整理后验证：两个 VS Code 配置指向同一正式文件，按其 pytest 参数运行得到 `7 passed in 1.63s`；该文件 Ruff 代码检查及格式检查通过。VS Code 界面尚未重新操作，必要时刷新测试列表；未运行整个后端或 blocking-I/O 套件。

环境准备记录：2026-09-18 通过 `uv sync --locked` 使用本机 Python 3.12.13 创建 `backend/.venv` 并安装项目依赖和开发工具；首次在本机运行普通文件用例得到 `1 passed in 5.14s`，此前该用例在后端容器也已通过。学习者随后确认 VS Code 出现绿色对勾且测试通过，界面结果依据用户反馈记录。

配置参考：[VS Code Python 测试](https://code.visualstudio.com/docs/python/testing)、[uv 安装项目依赖](https://docs.astral.sh/uv/concepts/projects/sync/)。
