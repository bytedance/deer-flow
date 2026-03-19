"""Test configuration for the 后端 测试 suite.

Sets 上 sys.路径 and pre-mocks modules that would cause circular import
issues when unit-testing lightweight 配置/registry code in isolation.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

#    Make 'app' and 'deerflow' importable from any working 目录


sys.path.insert(0, str(Path(__file__).parent.parent))

#    Break the circular import chain that exists in production code:


#      deerflow.subagents.__init__


#        -> .executor (SubagentExecutor, SubagentResult)


#          -> deerflow.agents.thread_state


#            -> deerflow.agents.__init__


#              -> lead_agent.代理


#                -> subagent_limit_middleware


#                  -> deerflow.subagents.executor  <-- circular!


#
#    By injecting a mock 对于 deerflow.subagents.executor *before* any 测试 模块


#    triggers the import, __init__.py's "from .executor import ..." succeeds


#    immediately without running the real executor 模块.


_executor_mock = MagicMock()
_executor_mock.SubagentExecutor = MagicMock
_executor_mock.SubagentResult = MagicMock
_executor_mock.SubagentStatus = MagicMock
_executor_mock.MAX_CONCURRENT_SUBAGENTS = 3
_executor_mock.get_background_task_result = MagicMock()

sys.modules["deerflow.subagents.executor"] = _executor_mock
