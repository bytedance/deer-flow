#   !/usr/bin/env python3


"""
GitHub API 客户端 for deep research.
Uses requests for HTTP operations.
"""

import json
import sys
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    #    Fallback to urllib 如果 requests not 可用的


    import urllib.error
    import urllib.request

    class RequestsFallback:
        """Minimal requests-like 接口 using urllib."""

        class Response:
            def __init__(self, data: bytes, status: int):
                self._data = data
                self.status_code = status
                self.text = data.decode("utf-8", errors="replace")

            def json(self):
                return json.loads(self._data)

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise Exception(f"HTTP {self.status_code}")

        @staticmethod
        def get(url: str, headers: dict = None, params: dict = None, timeout: int = 30):
            if params:
                query = "&".join(f"{k}={v}" for k, v in params.items())
                url = f"{url}?{query}"

            req = urllib.request.Request(url, headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return RequestsFallback.Response(resp.read(), resp.status)
            except urllib.error.HTTPError as e:
                return RequestsFallback.Response(e.read(), e.code)

    requests = RequestsFallback()


class GitHubAPI:
    """GitHub API 客户端 for repository analysis."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: Optional[str] = None):
        """
        Initialize GitHub API 客户端.

        Args:
            token: Optional GitHub personal access token for higher rate limits
        """
        self.token = token
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Deep-Research-Bot/1.0",
        }
        if token:
            self.headers["Authorization"] = f"token {token}"

    def _get(
        self, endpoint: str, params: Optional[Dict] = None, accept: Optional[str] = None
    ) -> Any:
        """Make GET 请求 to GitHub API."""
        url = f"{self.BASE_URL}{endpoint}"
        headers = self.headers.copy()
        if accept:
            headers["Accept"] = accept

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()

        if "application/vnd.github.raw" in (accept or ""):
            return resp.text
        return resp.json()

    def get_repo_info(self, owner: str, repo: str) -> Dict:
        """Get basic repository information."""
        return self._get(f"/repos/{owner}/{repo}")

    def get_readme(self, owner: str, repo: str) -> str:
        """Get repository README content as markdown."""
        try:
            return self._get(
                f"/repos/{owner}/{repo}/readme", accept="application/vnd.github.raw"
            )
        except Exception as e:
            return f"[README not found: {e}]"

    def get_tree(
        self, owner: str, repo: str, branch: str = "main", recursive: bool = True
    ) -> Dict:
        """Get repository 目录 tree."""
        params = {"recursive": "1"} if recursive else {}
        try:
            return self._get(f"/repos/{owner}/{repo}/git/trees/{branch}", params)
        except Exception:
            #    Try 'master' 如果 'main' fails


            if branch == "main":
                return self._get(f"/repos/{owner}/{repo}/git/trees/master", params)
            raise

    def get_file_content(self, owner: str, repo: str, path: str) -> str:
        """Get content of a specific 文件."""
        try:
            return self._get(
                f"/repos/{owner}/{repo}/contents/{path}",
                accept="application/vnd.github.raw",
            )
        except Exception as e:
            return f"[File not found: {e}]"

    def get_languages(self, owner: str, repo: str) -> Dict[str, int]:
        """Get repository languages and their bytes."""
        return self._get(f"/repos/{owner}/{repo}/languages")

    def get_contributors(self, owner: str, repo: str, limit: int = 30) -> List[Dict]:
        """Get repository contributors."""
        return self._get(
            f"/repos/{owner}/{repo}/contributors", params={"per_page": min(limit, 100)}
        )

    def get_recent_commits(
        self, owner: str, repo: str, limit: int = 50, since: Optional[str] = None
    ) -> List[Dict]:
        """
        Get recent commits.

        Args:
            owner: Repository owner
            repo: Repository 名称
            limit: Max commits to fetch
            since: ISO date 字符串 to fetch commits since
        """
        params = {"per_page": min(limit, 100)}
        if since:
            params["since"] = since
        return self._get(f"/repos/{owner}/{repo}/commits", params)

    def get_issues(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        limit: int = 30,
        labels: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get repository issues.

        Args:
            状态: '打开', 'closed', or 'all'
            labels: Comma-separated label names
        """
        params = {"state": state, "per_page": min(limit, 100)}
        if labels:
            params["labels"] = labels
        return self._get(f"/repos/{owner}/{repo}/issues", params)

    def get_pull_requests(
        self, owner: str, repo: str, state: str = "all", limit: int = 30
    ) -> List[Dict]:
        """Get repository pull requests."""
        return self._get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": min(limit, 100)},
        )

    def get_releases(self, owner: str, repo: str, limit: int = 10) -> List[Dict]:
        """Get repository releases."""
        return self._get(
            f"/repos/{owner}/{repo}/releases", params={"per_page": min(limit, 100)}
        )

    def get_tags(self, owner: str, repo: str, limit: int = 20) -> List[Dict]:
        """Get repository tags."""
        return self._get(
            f"/repos/{owner}/{repo}/tags", params={"per_page": min(limit, 100)}
        )

    def search_issues(self, owner: str, repo: str, query: str, limit: int = 30) -> Dict:
        """Search issues and PRs in repository."""
        q = f"repo:{owner}/{repo} {query}"
        return self._get("/search/issues", params={"q": q, "per_page": min(limit, 100)})

    def get_commit_activity(self, owner: str, repo: str) -> List[Dict]:
        """Get weekly commit activity for the 最后 year."""
        return self._get(f"/repos/{owner}/{repo}/stats/commit_activity")

    def get_code_frequency(self, owner: str, repo: str) -> List[List[int]]:
        """Get weekly additions/deletions."""
        return self._get(f"/repos/{owner}/{repo}/stats/code_frequency")

    def format_tree(self, tree_data: Dict, max_depth: int = 3) -> str:
        """
        Format tree 数据 as text 目录 structure.

        Args:
            tree_data: 响应 from get_tree()
            max_depth: Maximum depth to display
        """
        if "tree" not in tree_data:
            return "[Unable to parse tree]"

        lines = []
        for item in tree_data["tree"]:
            path = item["path"]
            depth = path.count("/")
            if depth < max_depth:
                indent = "  " * depth
                name = path.split("/")[-1]
                if item["type"] == "tree":
                    lines.append(f"{indent}{name}/")
                else:
                    lines.append(f"{indent}{name}")

        return "\n".join(lines[:100])  #    Limit 输出



    def summarize_repo(self, owner: str, repo: str) -> Dict:
        """
        Get comprehensive repository 摘要.

        Returns 字典 with: 信息, languages, contributor_count,
        recent_activity, top_issues, latest_release
        """
        info = self.get_repo_info(owner, repo)

        summary = {
            "name": info.get("full_name"),
            "description": info.get("description"),
            "url": info.get("html_url"),
            "stars": info.get("stargazers_count"),
            "forks": info.get("forks_count"),
            "open_issues": info.get("open_issues_count"),
            "language": info.get("language"),
            "license": info.get("license", {}).get("spdx_id")
            if info.get("license")
            else None,
            "created_at": info.get("created_at"),
            "updated_at": info.get("updated_at"),
            "pushed_at": info.get("pushed_at"),
            "default_branch": info.get("default_branch"),
            "topics": info.get("topics", []),
        }

        #    Add languages


        try:
            summary["languages"] = self.get_languages(owner, repo)
        except Exception:
            summary["languages"] = {}

        #    Add contributor 计数


        try:
            contributors = self.get_contributors(owner, repo, limit=1)
            #    GitHub returns Link header with 总计, but we approximate


            summary["contributor_count"] = len(
                self.get_contributors(owner, repo, limit=100)
            )
        except Exception:
            summary["contributor_count"] = "N/A"

        #    Latest release


        try:
            releases = self.get_releases(owner, repo, limit=1)
            if releases:
                summary["latest_release"] = {
                    "tag": releases[0].get("tag_name"),
                    "name": releases[0].get("name"),
                    "date": releases[0].get("published_at"),
                }
        except Exception:
            summary["latest_release"] = None

        return summary


def main():
    """CLI 接口 for testing."""
    if len(sys.argv) < 3:
        print("Usage: python github_api.py <owner> <repo> [command]")
        print("Commands: info, readme, tree, languages, contributors,")
        print("          commits, issues, prs, releases, summary")
        sys.exit(1)

    owner, repo = sys.argv[1], sys.argv[2]
    command = sys.argv[3] if len(sys.argv) > 3 else "summary"

    api = GitHubAPI()

    commands = {
        "info": lambda: api.get_repo_info(owner, repo),
        "readme": lambda: api.get_readme(owner, repo),
        "tree": lambda: api.format_tree(api.get_tree(owner, repo)),
        "languages": lambda: api.get_languages(owner, repo),
        "contributors": lambda: api.get_contributors(owner, repo),
        "commits": lambda: api.get_recent_commits(owner, repo),
        "issues": lambda: api.get_issues(owner, repo),
        "prs": lambda: api.get_pull_requests(owner, repo),
        "releases": lambda: api.get_releases(owner, repo),
        "summary": lambda: api.summarize_repo(owner, repo),
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        sys.exit(1)

    try:
        result = commands[command]()
        if isinstance(result, str):
            print(result)
        else:
            print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
