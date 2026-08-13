"""Community skill registry — discover and install skills from Git repositories."""

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from deerflow.skills.loader import get_skills_root_path
from deerflow.skills.validation import _validate_skill_frontmatter

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_URL = "https://raw.githubusercontent.com/bytedance/deer-flow/main/skills/registry.json"


def fetch_registry(registry_url: str | None = None) -> list[dict[str, Any]]:
    """Fetch the skill registry index from a URL.

    Returns list of skill entries with: name, description, repo, version, tags.
    Falls back to empty list on network errors.
    """
    url = registry_url or DEFAULT_REGISTRY_URL
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        logger.warning("Failed to fetch skill registry from %s", url)
        return []


def search_registry(query: str, registry_url: str | None = None) -> list[dict[str, Any]]:
    """Search the registry for skills matching a query string."""
    entries = fetch_registry(registry_url)
    query_lower = query.lower()
    return [entry for entry in entries if query_lower in entry.get("name", "").lower() or query_lower in entry.get("description", "").lower() or any(query_lower in tag.lower() for tag in entry.get("tags", []))]


def install_skill_from_repo(
    repo_url: str,
    *,
    skill_path: str = "",
    skills_root: Path | None = None,
) -> dict[str, Any]:
    """Clone a Git repo and install the skill from it.

    Args:
        repo_url: GitHub URL or owner/repo shorthand
        skill_path: Path within the repo to the skill directory (default: repo root)
        skills_root: Override skills root directory

    Returns:
        Dict with success, skill_name, message.
    """
    if skills_root is None:
        skills_root = get_skills_root_path()

    if not repo_url.startswith(("http://", "https://", "git@")):
        repo_url = f"https://github.com/{repo_url}.git"
    elif not repo_url.endswith(".git"):
        repo_url = f"{repo_url}.git"

    community_dir = skills_root / "community"
    community_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "repo"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise ValueError(f"Failed to clone {repo_url}: {result.stderr.strip()}")

        skill_dir = tmp_path / skill_path if skill_path else tmp_path

        is_valid, message, skill_name = _validate_skill_frontmatter(skill_dir)
        if not is_valid:
            raise ValueError(f"Invalid skill: {message}")
        if not skill_name or "/" in skill_name or "\\" in skill_name or ".." in skill_name:
            raise ValueError(f"Invalid skill name: {skill_name}")

        target = community_dir / skill_name
        if target.exists():
            shutil.rmtree(target)

        shutil.copytree(skill_dir, target, ignore=shutil.ignore_patterns(".git", ".github", "__pycache__"))
        logger.info("Skill %r installed from %s to %s", skill_name, repo_url, target)

    return {
        "success": True,
        "skill_name": skill_name,
        "message": f"Skill '{skill_name}' installed from {repo_url}",
    }
