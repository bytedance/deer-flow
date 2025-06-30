import fvg.common
import json
from langchain_core.tools import BaseTool
from pydantic import Field


class RoleScheduler(BaseTool):

    name: str = "role_scheduler"
    description: str = (
        "This tool is used to help arrange the order of speakers and assign "
        "tasks. The input string should be in JSON.\n"
        "For the planning stage, you should input a list with role and task, "
        "for example `[{\"name\": \"Bob\", \"task\": \"Use search tools to obtain information related to the issues mentioned by the user.\"}, {\"name\": \"Alice\", \"task\": \"Write Python code to analyse the collected information.\"}, ...]`,"
        "and this tool will notify the next role and its task after each role "
        "has completed their task.\n"
        "For completing your current task, just call this function without "
        "input."
    )
    session_locals: dict = Field(default_factory=dict)

    def _run(self, query: str, run_manager=None):
        session_local = fvg.common.get_session_local(
            self.session_locals, run_manager)

        if query:
            query_obj = json.loads(query)
            if isinstance(query_obj, list):
                session_local["plan"] = query_obj

        if "plan" in session_local and len(session_local["plan"]) > 0:
            return json.dumps(session_local["plan"].pop(0), ensure_ascii=False)
        else:
            return "{\"task\": \"There is no plan in progress. Please check whether the existing information is sufficient to provide an answer, or if more follow-up tasks need to be arranged to help answer the question.\"}"
