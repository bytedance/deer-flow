from mcp.server.fastmcp import FastMCP
import sandbox_fusion
from pydantic import BaseModel


class RunCodeReponse(BaseModel):
    # 0: OK
    # 1: Code Execution Fail
    # 2: Disconnected from the Environment
    status_code: int = 2
    stdout: str = ""
    stderr: str = ""
    # fetch_files: to be added


async def run_code_sandbox_fusion(
    code: str, files_mapper: dict[str, bytes] = {}
) -> str:
    """Run python code. Returns standard input and output only.

    Args:
        code (str): Python codes
        files_mapper (dict): Lists of files descriptors (key = file_path; value = file content in base64)

    Returns:
        str: Response coontaining status code(0: OK; 1: Code Execution fails; 2: Disconnected from the environment), stdout and stderr of the execution results
    """

    response_message_template = RunCodeReponse()
    try:
        response = await sandbox_fusion.run_code_async(
            sandbox_fusion.RunCodeRequest(
                compile_timeout=10,
                run_timeout=10,
                code=code,
                stdin=None,
                language="python",
                files=files_mapper,
                fetch_files=[],
            )
        )

        if response.status == sandbox_fusion.RunStatus.Success:
            response_message_template.status_code = 0
        elif response.status == sandbox_fusion.RunStatus.Failed:
            response_message_template.status_code = 1
        else:
            response_message_template.status_code = 2

        response_message_template.stdout = response.run_result.stdout
        response_message_template.stderr = response.run_result.stderr

    except Exception as e:
        response_message_template.status_code = 2
        response_message_template.stderr = str(e)
        response_message_template.stdout = ""

    return response_message_template.model_dump_json()


# Main entry point
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run MCP SSE-based server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8015, help="Port to listen on")
    parser.add_argument(
        "--sandbox_host",
        type=str,
        default="127.0.0.1",
        help="Sandbox http host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--sandbox_port",
        type=str,
        default="8080",
        help="Sandbox http port (default:8080)",
    )
    args = parser.parse_args()
    sandbox_endpoint = "http://" + args.sandbox_host + ":" + args.sandbox_port
    sandbox_fusion.set_endpoint(sandbox_endpoint)

    settings = dict(host=args.host, port=args.port)
    mcp = FastMCP("Sandbox", **settings)
    mcp.add_tool(run_code_sandbox_fusion)
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
