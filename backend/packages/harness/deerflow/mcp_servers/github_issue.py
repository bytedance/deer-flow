import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("github-issue")


async def fetch_github_issue(
    client: httpx.AsyncClient, repository: str, issue_number: int
) -> dict:
    response = await client.get(f"/repos/{repository}/issues/{issue_number}")
    response.raise_for_status()
    response_dict = response.json()
    return {
        "repository": repository,
        "number": issue_number,
        "title": response_dict["title"],
        "body": response_dict["body"],
        "state": response_dict["state"],
        "labels": [label["name"] for label in response_dict["labels"]],
        "url": response_dict["html_url"],
        "author": response_dict["user"]["login"],
    }


@mcp.tool()
async def get_github_issue(repository: str, issue_number: int) -> dict:
    # 使用 async with 管理客户端，否则请求结束后连接不会正常关闭
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(
        base_url="https://api.github.com", headers=headers
    ) as client:
        return await fetch_github_issue(client, repository, issue_number)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
