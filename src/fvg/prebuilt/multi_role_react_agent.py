import json
import langchain_core.messages
import langgraph.graph.message
import langgraph.graph
import langgraph.prebuilt


class ModelNode:
    def __init__(
        self, role_model_dict: dict, role_system_prompts: dict, starter: str
    ):
        self.role_model_dict = role_model_dict
        self.role_system_prompts = role_system_prompts
        self.starter = starter

    def __call__(self, state, config):
        # Merge the system prompt:
        is_first_call = not any([
            isinstance(i, langchain_core.messages.AIMessage)
            for i in state['messages']
        ])
        system_messages = [
            i.content for i in state['messages']
            if isinstance(i, langchain_core.messages.SystemMessage)
        ]
        if is_first_call and len(system_messages) > 0:
            for name in self.role_system_prompts.keys():
                self.role_system_prompts[name] = '\n'.join(
                    [self.role_system_prompts[name]] + system_messages)

        # Who is the next:
        # The next person is by the role_scheduler, and when the schedule ends,
        # the starter begins to speak. If the role_scheduler is not called,
        # continue with the previous speaker.
        if (
            len(state['messages']) > 0 and isinstance(
                state['messages'][-1], langchain_core.messages.ToolMessage) and
            state['messages'][-1].name == 'role_scheduler' and
            state['messages'][-1].status != 'error'
        ):
            next_step = json.loads(state['messages'][-1].content)
            name = next_step['name'] if 'name' in next_step else self.starter
        else:
            ai_messages = [
                i for i in state['messages']
                if isinstance(i, langchain_core.messages.AIMessage)
            ]
            name = (
                ai_messages[-1].name
                if len(ai_messages) > 0
                else self.starter
            )

        client = self.role_model_dict[name]
        messages = [
            langchain_core.messages.SystemMessage(
                self.role_system_prompts[name])
        ] + [
            i for i in state['messages']
            if isinstance(i, dict) and i['role'] != 'system' or
            not isinstance(i, langchain_core.messages.SystemMessage)
        ]

        response = client.invoke(messages, {'tags': [name], **config})
        response.name = name
        return {'messages': [response]}


def should_continue(state):
    messages = state['messages']
    last_message = messages[-1]
    if (
        isinstance(last_message, langchain_core.messages.AIMessage) and
        last_message.tool_calls
    ):
        return 'tools'
    else:
        return langgraph.graph.END


def create_agent(
    role_model_dict: dict, role_system_prompts: dict, starter: str,
    role_tools_dict: dict, tools: list, compile_args: dict
):
    role_model_dict = {
        name: model.bind_tools([
            i for i in tools
            if i.name in role_tools_dict[name]
        ])
        for name, model in role_model_dict.items()
    }
    model_node = ModelNode(
        role_model_dict, role_system_prompts, starter)
    tool_node = langgraph.prebuilt.ToolNode(tools)
    return langgraph.graph.StateGraph(langgraph.graph.message.MessagesState)\
        .add_node('model', model_node)\
        .add_node('tools', tool_node)\
        .add_edge(langgraph.graph.START, 'model')\
        .add_edge('tools', 'model')\
        .add_conditional_edges('model', should_continue)\
        .compile(**compile_args)
