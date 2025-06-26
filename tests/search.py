import json
from src.tools.search import get_web_search_tool
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage

tool_response = []
search_engine = get_web_search_tool(5)
searched_content = search_engine.invoke({'query': '2024年 美股形势'})
print(searched_content)
if isinstance(searched_content, list):
    background_results = [
        {"title": elem["title"], "content": elem["content"]}
        for elem in searched_content
    ]
    background_summary = f"Background investigation results:\n{json.dumps(background_results, ensure_ascii=False)}"
    tool_response.append(HumanMessage(content=background_summary))

print(tool_response)