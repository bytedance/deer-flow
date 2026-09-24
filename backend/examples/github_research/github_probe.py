from deerflow.community.github_research.client import (
    fetch_repository,
    parse_repository_url,
)
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit
import os
from pathlib import Path

from dotenv import load_dotenv

# 当前文件位于 backend/work，向上找到项目根目录。
project_root = Path(__file__).resolve().parents[3]
load_dotenv(project_root / ".env", override=True)
import asyncio
import json

import httpx




async def main():
    repository_url = input("请输入 GitHub 仓库地址：")

    try:
        owner, repo = parse_repository_url(repository_url)
        result = await fetch_repository(owner, repo)

    except httpx.TimeoutException:
        print("请求 GitHub 超时，请稍后再试。")
        return

    except httpx.HTTPStatusError as exc:
        response = exc.response
        status = response.status_code

        if status == 404:
            print("仓库不存在，或当前账号无权访问，请检查仓库地址。")

        elif status == 401:
            print("GitHub Token 无效或已过期，请检查本地 .env。")

        elif status in {403, 429}:
            remaining = response.headers.get("x-ratelimit-remaining")
            reset_at = response.headers.get("x-ratelimit-reset")
            retry_after = response.headers.get("retry-after")

            if remaining == "0":
                print("GitHub API 请求额度已用完，请暂停请求。")

                if reset_at and reset_at.isdigit():
                    reset_time = datetime.fromtimestamp(
                        int(reset_at),
                        tz=timezone.utc,
                    ).astimezone()

                    print(
                        "额度预计恢复时间：",
                        reset_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                    )

            elif retry_after:
                print(f"GitHub 暂时限制请求，请至少等待 {retry_after} 秒。")

            else:
                print("GitHub 拒绝了请求，可能是权限限制或触发了额外限流。")
                print("请检查权限，并暂停连续重试。")

        elif status >= 500:
            print(f"GitHub 服务暂时异常，状态码：{status}。请稍后再试。")

        else:
            print(f"GitHub 请求失败，状态码：{status}。")

        return

    except httpx.RequestError:
        print("无法连接 GitHub，请检查网络或代理设置。")
        return

    except ValueError as exc:
        print(f"输入或配置有误，或响应无法解析：{exc}")
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())