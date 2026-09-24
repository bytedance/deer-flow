import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from deerflow.community.github_research.client import fetch_readme


async def main():
    project_root = Path(__file__).resolve().parents[3]
    load_dotenv(project_root / ".env", override=True)

    result = await fetch_readme(
        "https://github.com/fastapi/fastapi"
    )

    # 终端只展示正文前 500 个字符，方便查看。
    preview = {
        **result,
        "content": result["content"][:500],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())