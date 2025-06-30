# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import os
from typing import Annotated, Literal

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.types import Command, interrupt
from langchain_mcp_adapters.client import MultiServerMCPClient

from src.agents import create_agent
from src.tools.search import LoggedTavilySearch
from src.tools import (
    crawl_tool,
    get_web_search_tool,
    get_retriever_tool,
    python_repl_tool,
)

from src.config.agents import AGENT_LLM_MAP
from src.config.configuration import Configuration
from src.llms.llm import get_llm_by_type
from src.prompts.planner_model import Plan
from src.prompts.template import apply_prompt_template
from src.utils.json_utils import repair_json_output
from src.tools.image_fetcher import ImageFetcher # Added ImageFetcher

from .types import State
from ..config import SELECTED_SEARCH_ENGINE, SearchEngine

logger = logging.getLogger(__name__)


@tool
def handoff_to_planner(
    research_topic: Annotated[str, "The topic of the research task to be handed off."],
    locale: Annotated[str, "The user's detected language locale (e.g., en-US, zh-CN)."],
):
    """Handoff to planner agent to do plan."""
    # This tool is not returning anything: we're just using it
    # as a way for LLM to signal that it needs to hand off to planner agent
    return


def background_investigation_node(state: State, config: RunnableConfig):
    logger.info("background investigation node is running.")
    configurable = Configuration.from_runnable_config(config)
    query = state.get("research_topic")

    raw_image_urls_from_background = state.get("raw_image_urls_from_background", [])

    if SELECTED_SEARCH_ENGINE == SearchEngine.TAVILY.value:
        # LoggedTavilySearch now uses TavilySearchResultsWithImages,
        # which returns a list of dicts (pages and images)
        # when include_images=True is set in get_web_search_tool.
        search_tool_instance = get_web_search_tool(configurable.max_search_results)
        # Ensure the tool instance is correctly configured for images if it's Tavily
        if not (isinstance(search_tool_instance, LoggedTavilySearch) and \
                getattr(search_tool_instance, 'include_images', False)):
             # Fallback or re-init with include_images=True if necessary,
             # though get_web_search_tool should handle this.
             # For now, assume get_web_search_tool correctly configures Tavily for images.
             pass

        tool_output = search_tool_instance.invoke(query)

        text_results_for_bg = []
        if isinstance(tool_output, list):
            for item in tool_output:
                if item.get("type") == "page" and item.get("content"):
                    text_results_for_bg.append(f"## {item.get('title', 'Search Result')}\n\n{item.get('content')}")
                elif item.get("type") == "image" and item.get("image_url"):
                    # Add to a list that will be processed later
                    raw_image_urls_from_background.append({
                        "type": "raw_image_url",
                        "url": item["image_url"],
                        "description": item.get("image_description", item.get("title", query))
                    })
            background_investigation_text = "\n\n".join(text_results_for_bg)
        elif isinstance(tool_output, str): # Fallback for non-Tavily or if Tavily fails to return list
            background_investigation_text = tool_output
            logger.warning("Tavily search did not return a list as expected, got string.")
        else:
            logger.error(f"Tavily search returned malformed response: {tool_output}")
            background_investigation_text = "Search results could not be processed."

    else: # Other search engines
        tool_output = get_web_search_tool(configurable.max_search_results).invoke(query)
        if isinstance(tool_output, str):
             background_investigation_text = tool_output
        elif isinstance(tool_output, list): # DuckDuckGo might return a list of strings
             background_investigation_text = "\n\n".join(tool_output)
        else:
             background_investigation_text = json.dumps(tool_output, ensure_ascii=False)
        # For non-Tavily search, we'd need to crawl pages to get images,
        # which is better handled during the research_steps if specific pages are targeted.

    # Deduplicate raw_image_urls_from_background based on URL
    seen_urls = set()
    unique_raw_image_urls = []
    for item in raw_image_urls_from_background:
        if item["url"] not in seen_urls:
            unique_raw_image_urls.append(item)
            seen_urls.add(item["url"])

    return {
        "background_investigation_results": background_investigation_text,
        "raw_image_urls_from_background": unique_raw_image_urls
    }


def planner_node(
    state: State, config: RunnableConfig
) -> Command[Literal["human_feedback", "reporter"]]:
    """Planner node that generate the full plan."""
    logger.info("Planner generating full plan")
    configurable = Configuration.from_runnable_config(config)
    plan_iterations = state["plan_iterations"] if state.get("plan_iterations", 0) else 0
    messages = apply_prompt_template("planner", state, configurable)

    if state.get("enable_background_investigation") and state.get(
        "background_investigation_results"
    ):
        messages += [
            {
                "role": "user",
                "content": (
                    "background investigation results of user query:\n"
                    + state["background_investigation_results"]
                    + "\n"
                ),
            }
        ]

    if configurable.enable_deep_thinking:
        llm = get_llm_by_type("reasoning")
    elif AGENT_LLM_MAP["planner"] == "basic":
        llm = get_llm_by_type("basic").with_structured_output(
            Plan,
            method="json_mode",
        )
    else:
        llm = get_llm_by_type(AGENT_LLM_MAP["planner"])

    # if the plan iterations is greater than the max plan iterations, return the reporter node
    if plan_iterations >= configurable.max_plan_iterations:
        return Command(goto="reporter")

    full_response = ""
    if AGENT_LLM_MAP["planner"] == "basic" and not configurable.enable_deep_thinking:
        response = llm.invoke(messages)
        full_response = response.model_dump_json(indent=4, exclude_none=True)
    else:
        response = llm.stream(messages)
        for chunk in response:
            full_response += chunk.content
    logger.debug(f"Current state messages: {state['messages']}")
    logger.info(f"Planner response: {full_response}")

    try:
        curr_plan = json.loads(repair_json_output(full_response))
    except json.JSONDecodeError:
        logger.warning("Planner response is not a valid JSON")
        if plan_iterations > 0:
            return Command(goto="reporter")
        else:
            return Command(goto="__end__")
    if curr_plan.get("has_enough_context"):
        logger.info("Planner response has enough context.")
        new_plan = Plan.model_validate(curr_plan)
        return Command(
            update={
                "messages": [AIMessage(content=full_response, name="planner")],
                "current_plan": new_plan,
            },
            goto="process_images", # Changed from reporter
        )
    return Command(
        update={
            "messages": [AIMessage(content=full_response, name="planner")],
            "current_plan": full_response,
        },
        goto="human_feedback",
    )


def human_feedback_node(
    state,
) -> Command[Literal["planner", "research_team", "reporter", "__end__"]]:
    current_plan = state.get("current_plan", "")
    # check if the plan is auto accepted
    auto_accepted_plan = state.get("auto_accepted_plan", False)
    if not auto_accepted_plan:
        feedback = interrupt("Please Review the Plan.")

        # if the feedback is not accepted, return the planner node
        if feedback and str(feedback).upper().startswith("[EDIT_PLAN]"):
            return Command(
                update={
                    "messages": [
                        HumanMessage(content=feedback, name="feedback"),
                    ],
                },
                goto="planner",
            )
        elif feedback and str(feedback).upper().startswith("[ACCEPTED]"):
            logger.info("Plan is accepted by user.")
        else:
            raise TypeError(f"Interrupt value of {feedback} is not supported.")

    # if the plan is accepted, run the following node
    plan_iterations = state["plan_iterations"] if state.get("plan_iterations", 0) else 0
    goto_next = "research_team" # Renamed variable to avoid conflict
    try:
        current_plan_str = repair_json_output(current_plan) # Use a different variable name
        # increment the plan iterations
        plan_iterations += 1
        # parse the plan
        new_plan_obj = json.loads(current_plan_str) # Use a different variable name
        if new_plan_obj["has_enough_context"]:
            goto_next = "process_images" # Changed from reporter
    except json.JSONDecodeError:
        logger.warning("Planner response is not a valid JSON in human_feedback_node")
        # If plan is malformed after feedback, and we've tried, maybe end or try planner again?
        # For now, if it was supposed to go to reporter due to iterations, let it go via process_images.
        if plan_iterations > 1 : # the plan_iterations is increased before this check
             logger.warning("Malformed plan in human_feedback after multiple iterations, proceeding to image processing/reporter.")
             goto_next = "process_images" # Changed from reporter
        else:
            logger.error("Malformed plan in human_feedback early iteration, ending.")
            return Command(goto="__end__")

    return Command(
        update={
            "current_plan": Plan.model_validate(new_plan_obj), # Ensure using the parsed object
            "plan_iterations": plan_iterations,
            "locale": new_plan_obj["locale"], # Ensure using the parsed object
        },
        goto=goto_next, # Use the updated variable name
    )


def coordinator_node(
    state: State, config: RunnableConfig
) -> Command[Literal["planner", "background_investigator", "__end__"]]:
    """Coordinator node that communicate with customers."""
    logger.info("Coordinator talking.")
    configurable = Configuration.from_runnable_config(config)
    messages = apply_prompt_template("coordinator", state)
    response = (
        get_llm_by_type(AGENT_LLM_MAP["coordinator"])
        .bind_tools([handoff_to_planner])
        .invoke(messages)
    )
    logger.debug(f"Current state messages: {state['messages']}")

    goto = "__end__"
    locale = state.get("locale", "en-US")  # Default locale if not specified
    research_topic = state.get("research_topic", "")

    if len(response.tool_calls) > 0:
        goto = "planner"
        if state.get("enable_background_investigation"):
            # if the search_before_planning is True, add the web search tool to the planner agent
            goto = "background_investigator"
        try:
            for tool_call in response.tool_calls:
                if tool_call.get("name", "") != "handoff_to_planner":
                    continue
                if tool_call.get("args", {}).get("locale") and tool_call.get(
                    "args", {}
                ).get("research_topic"):
                    locale = tool_call.get("args", {}).get("locale")
                    research_topic = tool_call.get("args", {}).get("research_topic")
                    break
        except Exception as e:
            logger.error(f"Error processing tool calls: {e}")
    else:
        logger.warning(
            "Coordinator response contains no tool calls. Terminating workflow execution."
        )
        logger.debug(f"Coordinator response: {response}")

    return Command(
        update={
            "locale": locale,
            "research_topic": research_topic,
            "resources": configurable.resources,
        },
        goto=goto,
    )


def reporter_node(state: State, config: RunnableConfig):
    """Reporter node that write a final report."""
    logger.info("Reporter write final report")
    configurable = Configuration.from_runnable_config(config)
    current_plan = state.get("current_plan")
    input_ = {
        "messages": [
            HumanMessage(
                f"# Research Requirements\n\n## Task\n\n{current_plan.title}\n\n## Description\n\n{current_plan.thought}"
            )
        ],
        "locale": state.get("locale", "en-US"),
    }
    invoke_messages = apply_prompt_template("reporter", input_, configurable)
    observations = state.get("observations", [])

    # Add a reminder about the new report format, citation style, and table usage
    invoke_messages.append(
        HumanMessage(
            content="IMPORTANT: Structure your report according to the format in the prompt. Remember to include:\n\n1. Key Points - A bulleted list of the most important findings\n2. Overview - A brief introduction to the topic\n3. Detailed Analysis - Organized into logical sections\n4. Survey Note (optional) - For more comprehensive reports\n5. Key Citations - List all references at the end\n\nFor citations, DO NOT include inline citations in the text. Instead, place all citations in the 'Key Citations' section at the end using the format: `- [Source Title](URL)`. Include an empty line between each citation for better readability.\n\nPRIORITIZE USING MARKDOWN TABLES for data presentation and comparison. Use tables whenever presenting comparative data, statistics, features, or options. Structure tables with clear headers and aligned columns. Example table format:\n\n| Feature | Description | Pros | Cons |\n|---------|-------------|------|------|\n| Feature 1 | Description 1 | Pros 1 | Cons 1 |\n| Feature 2 | Description 2 | Pros 2 | Cons 2 |",
            name="system",
        )
    )

    for observation in observations:
        invoke_messages.append(
            HumanMessage(
                content=f"Below are some observations for the research task:\n\n{observation}",
                name="observation",
            )
        )
    logger.debug(f"Current invoke messages: {invoke_messages}")
    response = get_llm_by_type(AGENT_LLM_MAP["reporter"]).invoke(invoke_messages)
    response_content = response.content
    logger.info(f"reporter response: {response_content}")

    return {"final_report": response_content}


def research_team_node(state: State):
    """Research team node that collaborates on tasks."""
    logger.info("Research team is collaborating on tasks.")
    pass


async def _execute_agent_step(
    state: State, agent, agent_name: str
) -> Command[Literal["research_team"]]:
    """Helper function to execute a step using the specified agent."""
    current_plan = state.get("current_plan")
    observations = state.get("observations", [])

    # Find the first unexecuted step
    current_step = None
    completed_steps = []
    for step in current_plan.steps:
        if not step.execution_res:
            current_step = step
            break
        else:
            completed_steps.append(step)

    if not current_step:
        logger.warning("No unexecuted step found")
        return Command(goto="research_team")

    logger.info(f"Executing step: {current_step.title}, agent: {agent_name}")

    # Format completed steps information
    completed_steps_info = ""
    if completed_steps:
        completed_steps_info = "# Existing Research Findings\n\n"
        for i, step in enumerate(completed_steps):
            completed_steps_info += f"## Existing Finding {i + 1}: {step.title}\n\n"
            completed_steps_info += f"<finding>\n{step.execution_res}\n</finding>\n\n"

    # Prepare the input for the agent with completed steps info
    agent_input = {
        "messages": [
            HumanMessage(
                content=f"{completed_steps_info}# Current Task\n\n## Title\n\n{current_step.title}\n\n## Description\n\n{current_step.description}\n\n## Locale\n\n{state.get('locale', 'en-US')}"
            )
        ]
    }

    # Add citation reminder for researcher agent
    if agent_name == "researcher":
        if state.get("resources"):
            resources_info = "**The user mentioned the following resource files:**\n\n"
            for resource in state.get("resources"):
                resources_info += f"- {resource.title} ({resource.description})\n"

            agent_input["messages"].append(
                HumanMessage(
                    content=resources_info
                    + "\n\n"
                    + "You MUST use the **local_search_tool** to retrieve the information from the resource files.",
                )
            )

        agent_input["messages"].append(
            HumanMessage(
                content="IMPORTANT: DO NOT include inline citations in the text. Instead, track all sources and include a References section at the end using link reference format. Include an empty line between each citation for better readability. Use this format for each reference:\n- [Source Title](URL)\n\n- [Another Source](URL)",
                name="system",
            )
        )

    # Invoke the agent
    default_recursion_limit = 25
    try:
        env_value_str = os.getenv("AGENT_RECURSION_LIMIT", str(default_recursion_limit))
        parsed_limit = int(env_value_str)

        if parsed_limit > 0:
            recursion_limit = parsed_limit
            logger.info(f"Recursion limit set to: {recursion_limit}")
        else:
            logger.warning(
                f"AGENT_RECURSION_LIMIT value '{env_value_str}' (parsed as {parsed_limit}) is not positive. "
                f"Using default value {default_recursion_limit}."
            )
            recursion_limit = default_recursion_limit
    except ValueError:
        raw_env_value = os.getenv("AGENT_RECURSION_LIMIT")
        logger.warning(
            f"Invalid AGENT_RECURSION_LIMIT value: '{raw_env_value}'. "
            f"Using default value {default_recursion_limit}."
        )
        recursion_limit = default_recursion_limit

    logger.info(f"Agent input: {agent_input}")
    result = await agent.ainvoke(
        input=agent_input, config={"recursion_limit": recursion_limit}
    )

    # Process the result
    response_content = result["messages"][-1].content
    logger.debug(f"{agent_name.capitalize()} full response: {response_content}")

    # Update the step with the execution result
    current_step.execution_res = response_content
    logger.info(f"Step '{current_step.title}' execution completed by {agent_name}")

    return Command(
        update={
            "messages": [
                HumanMessage(
                    content=response_content,
                    name=agent_name,
                )
            ],
            "observations": observations + [response_content],
        },
        goto="research_team",
    )


async def _setup_and_execute_agent_step(
    state: State,
    config: RunnableConfig,
    agent_type: str,
    default_tools: list,
) -> Command[Literal["research_team"]]:
    """Helper function to set up an agent with appropriate tools and execute a step.

    This function handles the common logic for both researcher_node and coder_node:
    1. Configures MCP servers and tools based on agent type
    2. Creates an agent with the appropriate tools or uses the default agent
    3. Executes the agent on the current step

    Args:
        state: The current state
        config: The runnable config
        agent_type: The type of agent ("researcher" or "coder")
        default_tools: The default tools to add to the agent

    Returns:
        Command to update state and go to research_team
    """
    configurable = Configuration.from_runnable_config(config)
    mcp_servers = {}
    enabled_tools = {}

    # Extract MCP server configuration for this agent type
    if configurable.mcp_settings:
        for server_name, server_config in configurable.mcp_settings["servers"].items():
            if (
                server_config["enabled_tools"]
                and agent_type in server_config["add_to_agents"]
            ):
                mcp_servers[server_name] = {
                    k: v
                    for k, v in server_config.items()
                    if k in ("transport", "command", "args", "url", "env")
                }
                for tool_name in server_config["enabled_tools"]:
                    enabled_tools[tool_name] = server_name

    # Create and execute agent with MCP tools if available
    if mcp_servers:
        async with MultiServerMCPClient(mcp_servers) as client:
            loaded_tools = default_tools[:]
            for tool in client.get_tools():
                if tool.name in enabled_tools:
                    tool.description = (
                        f"Powered by '{enabled_tools[tool.name]}'.\n{tool.description}"
                    )
                    loaded_tools.append(tool)
            agent = create_agent(agent_type, agent_type, loaded_tools, agent_type)
            return await _execute_agent_step(state, agent, agent_type)
    else:
        # Use default tools if no MCP servers are configured
        agent = create_agent(agent_type, agent_type, default_tools, agent_type)
        return await _execute_agent_step(state, agent, agent_type)


async def researcher_node(
    state: State, config: RunnableConfig
) -> Command[Literal["research_team"]]:
    """Researcher node that do research"""
    logger.info("Researcher node is researching.")
    configurable = Configuration.from_runnable_config(config)
    tools = [get_web_search_tool(configurable.max_search_results), crawl_tool]
    retriever_tool = get_retriever_tool(state.get("resources", []))
    if retriever_tool:
        tools.insert(0, retriever_tool)
    logger.info(f"Researcher tools: {tools}")
    return await _setup_and_execute_agent_step(
        state,
        config,
        "researcher",
        tools,
    )


async def coder_node(
    state: State, config: RunnableConfig
) -> Command[Literal["research_team"]]:
    """Coder node that do code analysis."""
    logger.info("Coder node is coding.")
    return await _setup_and_execute_agent_step(
        state,
        config,
        "coder",
        [python_repl_tool],
    )


def process_images_node(state: State, config: RunnableConfig):
    """
    Processes raw image URLs collected from background investigation and research steps,
    downloads them, saves them to a public directory, and updates observations
    with Markdown image tags.
    """
    logger.info("Image processing node is running.")
    configurable = Configuration.from_runnable_config(config)

    # Consolidate all raw image URLs.
    # researcher_node will need to be modified to add its findings to a similar list.
    # For now, we primarily use what background_investigation_node provides.
    # Let's assume researcher_node's tool calls might append to 'raw_image_urls_from_background'
    # or a new state field like 'raw_image_urls_from_research_steps'.
    # For simplicity, let's assume all raw image URLs are collected into raw_image_urls_from_background for now.

    all_raw_image_data = state.get("raw_image_urls_from_background", [])
    # Potentially merge with other sources if researcher_node is updated to output them separately
    # e.g., all_raw_image_data.extend(state.get("raw_image_urls_from_research_steps", []))

    if not all_raw_image_data:
        logger.info("No raw image URLs to process.")
        return state.get("observations", []) # Return existing observations if no images

    image_fetcher = ImageFetcher(unsplash_api_key=configurable.unsplash_api_key)

    processed_image_markdowns = []
    # Try to get one good image for the report. Can be adjusted for more.
    # The plan is to have ONE image per report, but ImageFetcher can be called multiple times if needed.

    # Option 1: Iterate through collected URLs first
    processed_url_from_collected = None
    for image_data in all_raw_image_data:
        if image_data.get("type") == "raw_image_url" and image_data.get("url"):
            # Pass keywords if available, e.g. from plan title, for Unsplash fallback by ImageFetcher
            keywords_for_fallback = state.get("current_plan").title if state.get("current_plan") else state.get("research_topic","")

            # We only pass article_image_urls to prioritize them.
            # HTML content parsing is a secondary option within get_report_image_url if this fails.
            local_image_public_url = image_fetcher.get_report_image_url(
                article_image_urls=[image_data["url"]], # Pass as list
                keywords=keywords_for_fallback
            )
            if local_image_public_url:
                description = image_data.get("description", "Report image")
                processed_image_markdowns.append(f"![{description}]({local_image_public_url})")
                processed_url_from_collected = True # Found one
                logger.info(f"Processed an image from collected URLs: {local_image_public_url}")
                break # Stop after one successful image from collected URLs

    # Option 2: If no image from collected URLs, try a general Unsplash search based on topic
    if not processed_url_from_collected:
        logger.info("No image processed from collected URLs, trying Unsplash with general keywords.")
        keywords = state.get("current_plan").title if state.get("current_plan") else state.get("research_topic","")
        if keywords:
            local_image_public_url = image_fetcher.get_report_image_url(keywords=keywords)
            if local_image_public_url:
                processed_image_markdowns.append(f"![{keywords}]({local_image_public_url})")
                logger.info(f"Processed an image from Unsplash using general keywords: {local_image_public_url}")

    # Prepend or append image markdowns to existing observations
    # Appending might be better so text observations come first.
    current_observations = state.get("observations", [])
    updated_observations = current_observations + processed_image_markdowns

    # Log if no images were added
    if not processed_image_markdowns:
        logger.info("No images were successfully processed or fetched for the report.")

    return {"observations": updated_observations}
