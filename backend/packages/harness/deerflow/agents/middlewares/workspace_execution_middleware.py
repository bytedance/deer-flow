"""Native lead/subagent invocation gate outside ordinary error normalization."""

from langchain.agents.middleware import AgentMiddleware

from deerflow.runtime.invocation import check_invocation, check_invocation_sync, invoke_worker_model


class WorkspaceExecutionMiddleware(AgentMiddleware):
    async def abefore_agent(self, state, runtime):
        await check_invocation()

    async def abefore_model(self, state, runtime):
        await check_invocation()

    async def awrap_model_call(self, request, handler):
        await check_invocation()
        return await invoke_worker_model(lambda: handler(request))

    async def awrap_tool_call(self, request, handler):
        await check_invocation()
        return await handler(request)

    def before_agent(self, state, runtime):
        check_invocation_sync()

    def before_model(self, state, runtime):
        check_invocation_sync()

    def wrap_model_call(self, request, handler):
        check_invocation_sync()
        return handler(request)

    def wrap_tool_call(self, request, handler):
        check_invocation_sync()
        return handler(request)
