import contextlib
import io
from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
import langchain_core.runnables.config
import langchain_core.tools
from langchain_experimental.tools.python.tool import sanitize_input
from pydantic import Field
from typing import Optional


class PythonREPLTool(langchain_core.tools.BaseTool):
    """Tool for running python code in a REPL."""

    name: str = "Python_REPL"
    description: str = (
        "A Python shell. Use this to execute python commands. "
        "Input should be a valid python command. "
        "If you want to see the output of a value, you should print it out "
        "with `print(...)`."
    )
    sanitize_input: bool = True
    session_locals: dict = Field(default_factory=dict)

    def get_session_local(self, run_manager):
        if run_manager is None or "thread_id" not in run_manager.metadata:
            session_id = "main"
        else:
            session_id = run_manager.metadata["thread_id"]

        if session_id not in self.session_locals:
            self.session_locals[session_id] = dict()

        return self.session_locals[session_id]

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ):
        """Use the tool."""
        if self.sanitize_input:
            query = sanitize_input(query)

        exec_out = io.StringIO()
        try:
            with contextlib.redirect_stdout(exec_out):
                exec(query, {}, self.get_session_local(run_manager))
                return exec_out.getvalue()
        except Exception as e:
            return repr(e)

    async def _arun(
        self,
        query: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ):
        """Use the tool asynchronously."""
        if self.sanitize_input:
            query = sanitize_input(query)

        kwargs = make_session_kwargs(run_manager)
        return await langchain_core.runnables.config.run_in_executor(
            None, self.run, query, **kwargs)


def make_session_kwargs(
    run_manager: Optional[AsyncCallbackManagerForToolRun]
):
    session_config_keys = ["metadata", "run_id", "tags"]
    if run_manager is None:
        return {}
    else:
        return {
            k: getattr(run_manager, k)
            for k in session_config_keys
            if hasattr(run_manager, k)
        }
