## Sandbox User Guidance

### Version:
v0.1
### Start-up:
**Package Required:**
```shell
uv pip install sandbox_fusion
```

**Launch Server:**
```shell
uv run sandbox.py --host 0.0.0.0 --port 8015 --sandbox_host 10.210.0.52 --sandbox_port 25536 
# If connected to EAP

# uv run sandbox.py --host 0.0.0.0 --port 8015 --sandbox_host app-c322a4ff9a564ef09152d58738ec4596.ns-foundation-a86cb259.svc.cluster.local --sandbox_port 8080 
# If connected in public cloud
```
如果deerflow框架运行在公司**EAP公网**下，可以用启用第一行命令，在MCP中配置沙盒IP `10.210.0.52:25536`以连接到沙盒服务

如果运行在**公有云**上，可以启用第二行命令，配置IP `app-c322a4ff9a564ef09152d58738ec4596.ns-foundation-a86cb259.svc.cluster.local:8080`

可以在终端中运行测试脚本来判断是否连接到沙盒
```shell
# curl "http://<IP-Address>:<host>/SandboxFusion/run_code" \
#     -H 'Content-Type: application/json' \
#     --data '{"code": "print(\"Hello, world!\")", "language": "python"}'

## Example
curl "http://10.210.0.52:25536/SandboxFusion/run_code" \
    -H 'Content-Type: application/json' \
    --data '{"code": "print(\"Hello, world!\")", "language": "python"}'
# Should return
# {"status":"Success","message":"","compile_result":null,"run_result":{"status":"Finished","execution_time":0.019182205200195312,"return_code":0,"stdout":"Hello, world!\n","stderr":""},"executor_pod_name":null,"files":{}}(sandbox)
```
当启动后，MCP服务会自动运行在`http://0.0.0.0:8015`,开放标准`sse`连接，承担桥接沙盒的作用

### API Usage
**Doc:**
```python
async def run_code_sandbox_fusion(
    code: str, files_mapper: dict[str, bytes] = {}
) -> str:
    """Run python code. Returns standard input and output only.

    Args:
        code (str): Python codes
        files_mapper (dict): Lists of files descriptors (key = file_path (relative to the execution codes); value = file content in base64)

    Returns:
        str: Response coontaining status code(0: OK; 1: Code Execution fails; 2: Disconnected from the Sandbox), stdout and stderr of the execution results in json format
        **Example: **  
        "
        {
            status_code: 0,
            stdout: 'Hello World!'   
            stderr: ''
        }
        "
    """
```

**Compatible with LangChain and LLM**
```python
from langchain_mcp_adapters.client import MultiServerMCPClient

async def main():
    from langchain_openai.chat_models.azure import AzureChatOpenAI
    from langgraph.prebuilt import create_react_agent

    chat_model_options = {
        "azure_endpoint": "https://omnimaid.openai.azure.com/",
        "deployment_name": "gpt-4.1",
        "api_version": "2024-02-15-preview",
        "openai_api_key": "<API-KEYS>",
    }
    llm = AzureChatOpenAI(**chat_model_options)
    mcp_servers = {"Sandbox": {"url": "http://0.0.0.0:8015/sse", "transport": "sse"}}
    client = MultiServerMCPClient(mcp_servers)
    tools = await client.get_tools(server_name="Sandbox")
    agent = create_react_agent(name="gpt-4.1", model=llm, tools=tools)
    response = await agent.ainvoke(
        {
            "messages": "Use python to to calculate the 987th fibonacci number. Use sandbox function. You need to use 'print' function to output your result and see it"
        }
    )
    print(f"AI final respoonse: {response["messages"][-1].content}")
    
    """
    AI final respoonse: The 987th Fibonacci number is:
    83428786095010233039452893451168885358856822423517291331018551725755973092961397681432523209335078083037082049842613293369652888469867204072869026512035048078160170454915915213979475203909274364258193729858
    This was calculated using Python with a simple iterative approach and printed as the output.
    """

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```














