"""Path-scoped CI: the scope rules, the real script on a PR merge commit, and the workflow wiring."""

from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci_changed_scopes.py"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
FRONTEND_ROOT = REPO_ROOT / "frontend"

_spec = importlib.util.spec_from_file_location("ci_changed_scopes", SCRIPT)
scopes_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scopes_module)

# workflow file -> {job: scope it is gated on}
GATED_JOBS = {
    "backend-unit-tests.yml": {"default-install-collection": "backend", "backend-unit-tests": "backend"},
    "frontend-unit-tests.yml": {"frontend-unit-tests": "frontend"},
    "lint-check.yml": {"lint-backend": "backend", "lint-frontend": "frontend"},
}
ALWAYS_RUN_JOBS = {"lint-check.yml": {"agent-guidance", "label-declarations"}}


def _workflow(name: str) -> dict:
    # BaseLoader keeps GitHub Actions' `on` key instead of YAML 1.1 bool True.
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


# --- scope rules -----------------------------------------------------------


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        (["backend/app/gateway/app.py"], {"backend": True, "frontend": False}),
        (["backend/uv.lock", "docker/nginx/nginx.conf", "Makefile"], {"backend": True, "frontend": False}),
        (["frontend/src/app/page.tsx", "frontend/tests/unit/app/page.test.ts"], {"backend": False, "frontend": True}),
        # Frontend files that backend tests read keep the backend scope.
        (["frontend/package.json"], {"backend": True, "frontend": True}),
        (["frontend/src/content/en/harness/memory.mdx"], {"backend": True, "frontend": True}),
        (["frontend/src/core/memory/AGENTS.md"], {"backend": True, "frontend": True}),
        (["frontend/src/app/page.tsx", "backend/app/gateway/app.py"], {"backend": True, "frontend": True}),
        (["contracts/thread_goal_contract.json"], {"backend": True, "frontend": True}),
        (["examples/deerflow-extension-bookmarks/manifest.json"], {"backend": True, "frontend": True}),
        (["skills/public/data-analysis/SKILL.md"], {"backend": True, "frontend": True}),
        # A frontend test reads the backend's built-in capability catalog.
        (["backend/packages/harness/deerflow/capabilities/builtin.json"], {"backend": True, "frontend": True}),
        # A new top-level directory is unknown to both lists: backend runs (skip-list), frontend does not.
        (["brand-new-dir/tool.py"], {"backend": True, "frontend": False}),
        (["scripts/ci_changed_scopes.py"], {"backend": True, "frontend": True}),
        ([".github/workflows/e2e-tests.yml"], {"backend": True, "frontend": True}),
        ([], {"backend": True, "frontend": True}),
    ],
)
def test_scopes_follow_what_each_suite_reads(changed: list[str], expected: dict[str, bool]) -> None:
    assert scopes_module.scopes_for(changed) == expected


# Frontend files the backend suite opened when all six CI shards ran under
# `strace -f -e trace=%file` (Linux, Python 3.12, PostgreSQL and Redis up).
TRACED_BACKEND_READS_UNDER_FRONTEND = (
    "frontend/AGENTS.md",
    "frontend/Makefile",
    "frontend/next.config.js",
    "frontend/package.json",
    "frontend/pnpm-lock.yaml",
    "frontend/src/AGENTS.md",
    "frontend/src/components/workspace/AGENTS.md",
    "frontend/src/components/workspace/browser-view/AGENTS.md",
    "frontend/src/content/en/application/configuration.mdx",
    "frontend/src/content/en/harness/configuration.mdx",
    "frontend/src/content/en/harness/customization.mdx",
    "frontend/src/content/en/harness/memory.mdx",
    "frontend/src/content/en/harness/middlewares.mdx",
    "frontend/src/content/en/harness/tools.mdx",
    "frontend/src/content/en/tutorials/create-your-first-harness.mdx",
    "frontend/src/content/en/tutorials/use-tools-and-skills.mdx",
    "frontend/src/content/zh/application/configuration.mdx",
    "frontend/src/content/zh/harness/configuration.mdx",
    "frontend/src/content/zh/harness/customization.mdx",
    "frontend/src/content/zh/harness/memory.mdx",
    "frontend/src/content/zh/harness/middlewares.mdx",
    "frontend/src/content/zh/harness/tools.mdx",
    "frontend/src/content/zh/tutorials/create-your-first-harness.mdx",
    "frontend/src/content/zh/tutorials/use-tools-and-skills.mdx",
    "frontend/src/core/api/api-client.ts",
    "frontend/src/core/auth/AGENTS.md",
    "frontend/src/core/background-tasks/AGENTS.md",
    "frontend/src/core/extensions/bundled-documentation.json",
    "frontend/src/core/memory/AGENTS.md",
    "frontend/src/core/models/AGENTS.md",
    "frontend/tests/e2e/AGENTS.md",
)


@pytest.mark.parametrize("path", TRACED_BACKEND_READS_UNDER_FRONTEND)
def test_frontend_files_the_backend_suite_reads_keep_the_backend_scope(path: str) -> None:
    assert scopes_module.scopes_for([path])["backend"] is True


def _frontend_paths_named_in_python(source: Path) -> set[str]:
    """Frontend paths a Python file names, as a literal or a `ROOT / "frontend" / ...` chain."""
    named: set[str] = set()
    tree = ast.parse(source.read_text(encoding="utf-8"))
    # Only the outermost `/` chain names the full path; its left operands are partial chains.
    inner = {id(node.left) for node in ast.walk(tree) if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("frontend/"):
            named.add(node.value)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and id(node) not in inner:
            parts: list[ast.expr] = []
            chain: ast.expr = node
            while isinstance(chain, ast.BinOp) and isinstance(chain.op, ast.Div):
                parts.insert(0, chain.right)
                chain = chain.left
            parts.insert(0, chain)
            segments: list[str] = []
            for part in parts:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    segments.append(part.value)
                elif segments:
                    segments.append("<any>")
                    break
            if segments and segments[0] == "frontend":
                named.add("/".join(segments))
    return named


# Existing frontend paths backend code names as data, without opening them.
NAMED_BUT_NOT_READ = {
    # Matched against .dockerignore patterns; only .dockerignore is read.
    ("backend/tests/test_dockerignore_excludes_runtime_data.py", "frontend/src/env.js"),
    ("backend/tests/test_dockerignore_excludes_runtime_data.py", "frontend/tests/unit/core/extensions/bookmarks.test.ts"),
}


def test_backend_code_names_no_frontend_path_outside_the_backend_scope() -> None:
    # A static scan cannot tell a read from a mention, so it flags every existing
    # frontend path that backend code names and would not run the backend scope.
    own_files = {SCRIPT, Path(__file__).resolve()}
    sources = [*(REPO_ROOT / "backend").glob("tests/**/*.py"), *(REPO_ROOT / "scripts").glob("*.py"), *(REPO_ROOT / "backend" / "scripts").rglob("*.py")]
    named = {(source.relative_to(REPO_ROOT).as_posix(), path) for source in sources if source.resolve() not in own_files for path in _frontend_paths_named_in_python(source)}

    assert any(path.startswith("frontend/src/content/") for _, path in named), "the scanner no longer sees the documentation tests' path chains"
    skipped = set()
    for source, path in named:
        target = REPO_ROOT / path.split("/<any>", 1)[0]
        if not target.exists():
            continue
        probe = f"{path.split('/<any>', 1)[0].rstrip('/')}/any" if target.is_dir() else path
        if not scopes_module.scopes_for([probe])["backend"]:
            skipped.add((source, path))
    assert skipped - NAMED_BUT_NOT_READ == set(), "add the read paths to BACKEND_READS_UNDER_SKIPPED in scripts/ci_changed_scopes.py"
    assert NAMED_BUT_NOT_READ <= named, "drop entries from NAMED_BUT_NOT_READ that backend code no longer names"


# --- the real script on a PR-shaped checkout ---------------------------------


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _run_script(checkout: Path, event: str) -> dict[str, str]:
    result = subprocess.run(
        [sys.executable, "scripts/ci_changed_scopes.py", "--event", event],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
    for relative in ("backend/app.py", "frontend/src/page.tsx"):
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).write_text("v1\n", encoding="utf-8", newline="\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    return repo


def _open_pr_merge_commit(repo: Path, changes: dict[str, str], base_moves: dict[str, str]) -> None:
    """Shape HEAD like GitHub's refs/pull/N/merge: parent 1 is the base tip, parent 2 the PR head."""
    ident = ("-c", "user.name=t", "-c", "user.email=t@t")
    _git(repo, "checkout", "-q", "-b", "pr")
    for relative, text in changes.items():
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).write_text(text, encoding="utf-8", newline="\n")
    _git(repo, *ident, "add", ".")
    _git(repo, *ident, "commit", "-q", "-m", "pr")
    _git(repo, "checkout", "-q", "main")
    for relative, text in base_moves.items():
        (repo / relative).write_text(text, encoding="utf-8", newline="\n")
    _git(repo, *ident, "commit", "-q", "-am", "main moved on")
    _git(repo, *ident, "merge", "-q", "--no-ff", "-m", "merge pr", "pr")


def test_script_scopes_only_the_pr_changes_not_base_branch_progress(checkout: Path) -> None:
    # The base branch changed backend after the PR branched; only the PR's frontend change counts.
    _open_pr_merge_commit(checkout, {"frontend/src/page.tsx": "v2\n"}, base_moves={"backend/app.py": "v2\n"})

    assert _run_script(checkout, "pull_request") == {"backend": "false", "frontend": "true"}


def test_script_runs_every_scope_on_push(checkout: Path) -> None:
    _open_pr_merge_commit(checkout, {"frontend/src/page.tsx": "v2\n"}, base_moves={"backend/app.py": "v2\n"})

    assert _run_script(checkout, "push") == {"backend": "true", "frontend": "true"}


def test_script_fails_open_when_the_diff_is_unknown(checkout: Path) -> None:
    # A single root commit has no HEAD^1, as with a too-shallow checkout.
    assert _run_script(checkout, "pull_request") == {"backend": "true", "frontend": "true"}


# --- workflow wiring --------------------------------------------------------


@pytest.mark.parametrize("name", sorted(GATED_JOBS))
def test_workflow_gates_heavy_jobs_on_the_shared_change_job(name: str) -> None:
    jobs = _workflow(name)["jobs"]
    changes = jobs["changes"]

    checkout_step = next(step for step in changes["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout_step["with"]["fetch-depth"] == "2"
    assert any("scripts/ci_changed_scopes.py --event" in step.get("run", "") and step.get("id") == "scopes" for step in changes["steps"])
    assert set(changes["outputs"]) == set(scopes_module.SCOPES)

    for job, scope in GATED_JOBS[name].items():
        assert jobs[job]["needs"] == "changes", f"{name}:{job} must wait for the change job"
        assert jobs[job]["if"] == f"needs.changes.outputs.{scope} == 'true'"
    for job in ALWAYS_RUN_JOBS.get(name, ()):
        assert "needs" not in jobs[job] and "if" not in jobs[job], f"{name}:{job} is cheap and must always run"


@pytest.mark.parametrize("name", sorted(GATED_JOBS))
def test_workflow_cancels_superseded_runs(name: str) -> None:
    concurrency = _workflow(name)["concurrency"]

    assert "github.event.pull_request.number || github.ref" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "true"


# --- frontend reads stay inside the frontend scope ---------------------------

_RELATIVE_IMPORT = re.compile(r"""(?:from\s+|import\(\s*|require\(\s*)["']((?:\.\./)+[^"']+)["']""")
_DIRNAME_PATH = re.compile(r"""__dirname\s*,\s*["']((?:\.\./)+[^"']*)["']""")
_CWD_PATH = re.compile(r"""process\.cwd\(\)\s*,\s*["']((?:\.\./)+[^"']*)["']""")


def _frontend_reads_outside_frontend() -> dict[str, set[str]]:
    reads: dict[str, set[str]] = {}
    sources = [path for base in ("src", "tests/unit") for path in (FRONTEND_ROOT / base).rglob("*") if path.suffix in {".ts", ".tsx", ".js", ".mjs"}]
    sources += [path for path in FRONTEND_ROOT.glob("*.config.*") if path.is_file()]
    for source in sources:
        text = source.read_text(encoding="utf-8", errors="ignore")
        targets = [source.parent / match for pattern in (_RELATIVE_IMPORT, _DIRNAME_PATH) for match in pattern.findall(text)]
        targets += [FRONTEND_ROOT / match for match in _CWD_PATH.findall(text)]
        for target in targets:
            resolved = target.resolve()
            relative = resolved.relative_to(REPO_ROOT.resolve()).as_posix() + ("/" if resolved.is_dir() else "")
            if not relative.startswith("frontend/"):
                reads.setdefault(relative, set()).add(source.relative_to(FRONTEND_ROOT).as_posix())
    return reads


def test_frontend_only_reads_paths_inside_its_scope() -> None:
    reads = _frontend_reads_outside_frontend()

    assert reads, "the scanner found no reads outside frontend/; it no longer recognizes the read patterns"
    outside = {path: sorted(files) for path, files in reads.items() if not scopes_module.scopes_for([path])["frontend"]}
    assert outside == {}, "add these paths to FRONTEND_PREFIXES in scripts/ci_changed_scopes.py"
