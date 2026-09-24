import base64
import hashlib
import os
import re
from urllib.parse import urlsplit

import httpx

from deerflow.community.github_research.cache import ReadmeCache

_readme_cache = ReadmeCache(ttl_seconds=300, max_entries=16)


async def fetch_repository(owner: str, repo: str) -> dict:
    """获取一个公开 GitHub 仓库的基本信息。"""
    url = f"https://api.github.com/repos/{owner}/{repo}"

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("请先在项目根目录 .env 中配置 GITHUB_TOKEN")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "deerflow-repo-study",
                "Authorization": f"Bearer {token}",
            },
        )

        # 请求失败时抛出异常，避免把错误信息当作仓库数据。
        response.raise_for_status()
        data = response.json()

    # GitHub 可能没有识别出许可证，此时该字段为 null。
    license_info = data.get("license") or {}

    return {
        "full_name": data["full_name"],
        "description": data.get("description"),
        "stars": data["stargazers_count"],
        "language": data.get("language"),
        "license": license_info.get("spdx_id"),
        "archived": data["archived"],
        "pushed_at": data.get("pushed_at"),
        "source_url": data["html_url"],
    }


def parse_repository_url(url: str) -> tuple[str, str]:
    """将 GitHub 仓库主页地址解析为所有者和仓库名。"""
    parsed = urlsplit(url.strip())

    # 精确检查域名，避免误接受 github.com.example.com 等地址。
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise ValueError("请输入 https://github.com/ 开头的仓库地址")

    if parsed.query or parsed.fragment:
        raise ValueError("请使用不带查询参数或 # 锚点的仓库主页地址")

    # 允许地址末尾有一个斜杠。
    path = parsed.path.removesuffix("/")
    parts = path.split("/")

    if len(parts) != 3 or parts[0] != "":
        raise ValueError("地址格式应为 https://github.com/所有者/仓库名")

    owner, repo = parts[1], parts[2]

    # 兼容从 GitHub 复制的 HTTPS 克隆地址。
    repo = repo.removesuffix(".git")

    if not re.fullmatch(r"[A-Za-z0-9-]+", owner):
        raise ValueError("仓库所有者格式不正确")

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", repo) or repo in {".", ".."}:
        raise ValueError("仓库名格式不正确")

    return owner, repo


async def fetch_readme(
    repository_url: str,
    offset: int = 0,
    limit: int = 8000,
) -> dict:
    """从缓存或 GitHub 获取 README，然后返回指定片段。"""
    if type(offset) is not int or offset < 0:
        raise ValueError("offset 必须是大于等于 0 的整数。")
    if type(limit) is not int or not 1 <= limit <= 8000:
        raise ValueError("limit 必须是 1 到 8000 之间的整数。")

    owner, repo = parse_repository_url(repository_url)

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("请先在项目根目录 .env 中配置 GITHUB_TOKEN")

    # 不同 Token 使用不同缓存；不把 Token 原文放进缓存键。
    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    cache_key = f"{owner.lower()}/{repo.lower()}:{token_digest}"

    document = _readme_cache.get(cache_key)
    cache_hit = document is not None

    if document is None:
        url = f"https://api.github.com/repos/{owner}/{repo}/readme"

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "deerflow-repo-study",
                    "Authorization": f"Bearer {token}",
                },
            )
            response.raise_for_status()
            data = response.json()

        if data.get("encoding") != "base64":
            raise ValueError("README 编码不受支持，暂时无法读取。")

        encoded_content = data.get("content")
        if not isinstance(encoded_content, str):
            raise ValueError("GitHub 没有返回有效的 README 内容。")

        compact_content = "".join(encoded_content.split())
        raw_content = base64.b64decode(
            compact_content,
            validate=True,
        )
        text = raw_content.decode("utf-8")

        document = {
            "path": data["path"],
            "source_url": data["html_url"],
            "text": text,
        }

        # 仅保存请求和解码均成功的完整文档。
        _readme_cache.set(cache_key, document)

    text = document["text"]
    total_chars = len(text)

    if offset > total_chars:
        raise ValueError(f"offset 超出正文长度，正文共有 {total_chars} 个字符。")

    content = text[offset : offset + limit]
    end_offset = offset + len(content)
    has_more = end_offset < total_chars

    return {
        "full_name": f"{owner}/{repo}",
        "path": document["path"],
        "source_url": document["source_url"],
        "content": content,
        "total_chars": total_chars,
        "returned_chars": len(content),
        "offset": offset,
        "next_offset": end_offset if has_more else None,
        "has_more": has_more,
        "truncated": offset > 0 or has_more,
        "cache_hit": cache_hit,
    }


async def fetch_recent_commits(
    repository_url: str,
    limit: int = 5,
) -> dict:
    """查询仓库默认分支最近的提交记录。"""
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("limit 必须是 1 到 10 之间的整数。")

    owner, repo = parse_repository_url(repository_url)

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("请先在项目根目录 .env 中配置 GITHUB_TOKEN")

    url = f"https://api.github.com/repos/{owner}/{repo}/commits"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            url,
            params={"per_page": limit},
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "deerflow-repo-study",
                "Authorization": f"Bearer {token}",
            },
        )
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, list):
        raise ValueError("GitHub 没有返回有效的提交列表。")

    recent_commits = []

    for item in data:
        commit_info = item.get("commit") or {}
        committer_info = commit_info.get("committer") or {}
        github_author = item.get("author") or {}

        sha = item.get("sha")
        short_sha = sha[:12] if isinstance(sha, str) else None

        recent_commits.append(
            {
                "sha": short_sha,
                "committed_at": committer_info.get("date"),
                "author_login": github_author.get("login"),
                "source_url": item.get("html_url"),
            }
        )

    return {
        "full_name": f"{owner}/{repo}",
        "sample_size": len(recent_commits),
        "recent_commits": recent_commits,
        "scope": "default_branch",
        "evidence_note": ("这些记录只表示默认分支最近的提交，不能单独证明维护质量、发布频率或长期维护状态。"),
    }


async def fetch_latest_release(repository_url: str) -> dict:
    """查询 GitHub 仓库最新发布的正式 Release。"""
    owner, repo = parse_repository_url(repository_url)

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("请先在项目根目录 .env 中配置 GITHUB_TOKEN")

    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "deerflow-repo-study",
                "Authorization": f"Bearer {token}",
            },
        )

        # GitHub 在没有可用正式 Release 时也可能返回 404。
        if response.status_code == 404:
            return {
                "full_name": f"{owner}/{repo}",
                "available": False,
                "latest_release": None,
                "evidence_note": ("GitHub latest release 接口没有返回可用结果。这可能表示仓库没有已发布的正式 Release，也可能与仓库权限或资源状态有关；不能据此断言项目没有版本、标签或维护活动。"),
            }

        response.raise_for_status()
        data = response.json()

    author = data.get("author") or {}

    return {
        "full_name": f"{owner}/{repo}",
        "available": True,
        "latest_release": {
            "tag_name": data.get("tag_name"),
            "name": data.get("name"),
            "created_at": data.get("created_at"),
            "published_at": data.get("published_at"),
            "author_login": author.get("login"),
            "source_url": data.get("html_url"),
        },
        "evidence_note": ("该接口返回最近的非草稿、非预发布 Release。它不包含只有 Git 标签、没有 GitHub Release 的版本，也不能单独证明发布频率、版本质量或长期维护状态。"),
    }
