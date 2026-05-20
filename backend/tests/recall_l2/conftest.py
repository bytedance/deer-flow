"""L2 评测的 pytest collect 占位文件。

这套 L2 套件**不是常规 pytest 测试** —— 主入口是 ``eval_recall.py``,
通过 ``make eval-recall`` 或 GitHub workflow 手动跑。

之所以仍然保留 ``conftest.py``,是因为 ``backend/Makefile`` 的 ``test``
target 默认会扫描整个 ``tests/`` 目录;有这个文件可以让 pytest 在
collect 阶段稳定跳过 ``eval_recall.py``,避免 ``make test`` 顺手把
真实 embedding 调起来烧钱/烧时间。

如果以后想给 L2 加几条真正的轻量级 pytest 用例(比如 anchor 解析单测),
直接在本目录新建 ``test_*.py`` 即可,``eval_recall.py`` 仍然被忽略。
"""

from __future__ import annotations

# pytest 内置钩子:把这些文件从 collect 阶段排除掉。
collect_ignore = ["eval_recall.py"]
