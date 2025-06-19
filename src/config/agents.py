from typing import Dict, List, Literal
from dataclasses import dataclass
# Define available LLM types
LLMType = Literal["basic", "reasoning", "vision"]

# 定义可用的工具类型
ToolType = Literal["direct", "interactive"]

# 定义节点类型
NodeType = Literal["coordinator", 
                   "planner", 
                   "writer", 
                   "coder", 
                   "searcher", 
                   "reader", 
                   "thinker", 
                   "reporter", 
                   "supervisor"]

@dataclass
class ToolConfig:
    """工具配置"""
    name: str
    type: ToolType  # direct: 直接执行不等返回, interactive: 交互式等待返回
    enabled: bool = True
    max_retries: int = 3

@dataclass
class NodeConfig:
    """节点配置"""
    name: str
    llm_type: LLMType
    enabled_tools: List[str]
    next_nodes: List[str]  # 可以连接的下一个节点
    max_iterations: int = 5
    requires_approval: bool = False  # 是否需要supervisor审批

class AgentConfiguration:
    """全局配置类"""
    
    # Agent-LLM映射
    AGENT_LLM_MAP: Dict[str, LLMType] = {
        "coordinator": "basic",
        "planner": "basic", 
        "writer": "basic",
        "coder": "basic",
        "searcher": "basic",
        "reader": "vision",
        "thinker": "reasoning",
        "reporter": "basic",
        "supervisor": "basic",
    }
    
    # 节点配置 - 用户可自定义连接关系
    """
        先coordinator给planner传入具体的任务，然后planner设定完整的任务树
        Planer 会直接将第一个任务给到对应节点，其后就不会再回到planner，总体plan放入state中
        节点之间不能流转，都传回给supervisor，针对任务完成情况决定当前step需不需要重跑
        如不需要重跑则自动流转到下一个节点，每个节点的历史信息由planner一开始指定，默认会有上一个节点的执行结果作为history
        文件之间的流转通过state.resource实现
        每个节点的 next node 由planner指定,对应toolcall也需要根据plan控制
        节点输出为toolcall格式，是给下一个节点的任务，然后会转到supervisor根据具体plan将节点执行的输出和给的任务合在一起给到下一个节点
    """
    NODE_CONFIGS: Dict[str, NodeConfig] = {
        "coordinator": NodeConfig(
            name="coordinator",
            llm_type="basic",
            enabled_tools=[],#"web_search_tool", "message_ask_user_tool"
            next_nodes=["planner", "__end__"]
        ),
        "planner": NodeConfig(
            name="planner",
            llm_type="basic",
            enabled_tools=["background_research"],
            next_nodes=["writer", "coder", "researcher", "reader", "thinker", "reporter"]
        ),
        "supervisor": NodeConfig(
            name="supervisor",
            llm_type="basic",
            enabled_tools=["approve_step", "reject_step", "request_revision"],
            next_nodes=["writer", "coder", "researcher", "reader", "thinker", "reporter", "__end__"]
        ),
        "writer": NodeConfig(
            name="writer",
            llm_type="basic",
            enabled_tools=[],
            next_nodes=["supervisor"],
            requires_approval=True
        ),
        "coder": NodeConfig(
            name="coder",
            llm_type="basic",
            enabled_tools=["python_repl", "sandbox_tools"],
            next_nodes=["supervisor"],
            requires_approval=True
        ),
        "searcher": NodeConfig(
            name="searcher",
            llm_type="basic",
            enabled_tools=["web_search", "image_download", "mcp_tools"],
            next_nodes=["supervisor"],
            requires_approval=True
        ),
        # "reader": NodeConfig(
        #     name="reader",
        #     llm_type="vision",
        #     enabled_tools=["call_rotate_tool", "image_analysis"],
        #     next_nodes=["supervisor"],
        #     requires_approval=True
        # ),
        # "thinker": NodeConfig(
        #     name="thinker",
        #     llm_type="reasoning",
        #     enabled_tools=[],
        #     next_nodes=["supervisor"],
        #     requires_approval=True
        # ),

        "reporter": NodeConfig(
            name="reporter",
            llm_type="basic",
            enabled_tools=["generate_report"],
            next_nodes=["supervisor"]
        )
    }
    
    # 工具配置
    TOOL_CONFIGS: Dict[str, ToolConfig] = {
        # 初始化节点流传fc
        "call_planner_agent": ToolConfig("call_planner_agent", "direct"),
        "call_coder_agent": ToolConfig("call_coder_agent", "direct"),
        "call_researcher_agent": ToolConfig("call_researcher_agent", "direct"),
        "call_reader_agent": ToolConfig("call_reader_agent", "direct"),
        "call_rotate_tool": ToolConfig("call_rotate_tool", "interactive"),
        # 初始化本地工具tool
        "python_repl": ToolConfig("python_repl", "interactive"),
        "web_search": ToolConfig("web_search", "interactive"),

        "approve_step": ToolConfig("approve_step", "direct"),
        "reject_step": ToolConfig("reject_step", "direct"),
        "request_revision": ToolConfig("request_revision", "direct"),
        "background_research": ToolConfig("background_research", "interactive"),
        # 初始化MCP tool
        "mcp_tools": ToolConfig("mcp_tools", "interactive"),
        "sandbox_tools": ToolConfig("sandbox_tools", "interactive"),
        "image_download": ToolConfig("image_download", "interactive"),
        "image_analysis": ToolConfig("image_analysis", "interactive"),
        "generate_report": ToolConfig("generate_report", "direct"),
    }

    # 步骤类型到节点的映射
    STEP_TYPE_TO_NODE: Dict[str, str] = {
        "writer": "writer",
        "coder": "coder", 
        "researcher": "researcher",
        "reader": "reader",
        "thinker": "thinker"
    }