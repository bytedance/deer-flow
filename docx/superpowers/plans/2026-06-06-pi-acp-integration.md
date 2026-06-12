# pi-acp Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `pi-acp` (ACP adapter for the `pi` coding agent) into DeerFlow as a lightweight code-generation fast path, plus ship three offline x86_64 bundle scripts matching the existing `bundle-claude-code.sh` / `bundle-claude-agent-acp.sh` pattern.

**Architecture:** No new code modules. Reuse DeerFlow's existing `invoke_acp_agent` tool path (already wired for `codex` and `claude_code`). Add a `pi` entry to `acp_agents:` in `config.example.yaml`, extend `_build_acp_section` in `prompt.py` to instruct the lead agent to route small single-shot code tasks to `pi` and fall back to in-process tools on error. Add three shell scripts to `scripts/` that vendor `@earendil-works/pi-coding-agent`, `pi-acp`, and the standalone `@agegr/pi-web` into tarballs under `offline-claude/`. Add commented-out install blocks to `backend/Dockerfile` for the two ACP-path bundles (the `pi-web` bundle is **not** in the image — it's a standalone artifact for the user).

**Tech Stack:** Python 3.12 (harness), LangGraph, Pydantic, pytest, ruff, Bash, npm, Docker

**Source spec:** `docx/superpowers/specs/2026-06-06-pi-acp-integration-design.md`

---

## File Structure

**Files to create:**
- `scripts/bundle-pi-coding-agent.sh` — bundles `pi` agent binary (Linux x86_64 host guard)
- `scripts/bundle-pi-acp.sh` — bundles `pi-acp` ACP adapter (no host guard; pure JS)
- `scripts/bundle-pi-web.sh` — bundles `pi-web` standalone Web UI (Linux x86_64 host guard; **not** wired into Dockerfile)
- `docs/PI_ACP.md` — user-facing documentation for the new feature

**Files to modify:**
- `config.example.yaml` — add `acp_agents.pi` commented block; bump `config_version: 10` → `11`
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` — extend `_build_acp_section` to add pi-routing guidance + in-process fallback note
- `backend/tests/test_lead_agent_prompt.py` — add 3 new tests + extend 1 existing test
- `backend/Dockerfile` — add commented-out `pi-coding-agent` and `pi-acp` install blocks (builder + runtime stages)
- `backend/CLAUDE.md` — mention `pi` in the ACP agent tools section

**Out of scope (per spec section 8):** backend LLM classifier, fast-path API routes, `pi` as a subagent, renaming `offline-claude/` directory, frontend changes.

---

## Task 1: Write failing tests for pi routing guidance in `_build_acp_section`

**Files:**
- Modify: `backend/tests/test_lead_agent_prompt.py` (insert after the existing `test_build_acp_section_uses_explicit_app_config_without_global_config` at line 178)

**Why first:** TDD. The tests are the contract; the implementation in Task 2 is verified against them.

- [ ] **Step 1: Read the existing test pattern**

Open `backend/tests/test_lead_agent_prompt.py`, scroll to line 178. Read the existing `test_build_acp_section_uses_explicit_app_config_without_global_config` function (lines 178–189). The pattern is:

```python
def test_build_acp_section_uses_explicit_app_config_without_global_config(monkeypatch):
    explicit_config = SimpleNamespace(acp_agents={"codex": object()})
    def fail_get_acp_agents():
        raise AssertionError("ambient get_acp_agents() must not be used when app_config is explicit")
    monkeypatch.setattr("deerflow.config.acp_config.get_acp_agents", fail_get_acp_agents)
    section = prompt_module._build_acp_section(app_config=explicit_config)
    assert "ACP Agent Tasks" in section
    assert "/mnt/acp-workspace/" in section
```

The new tests follow the same shape. `SimpleNamespace` is already imported (line 2).

- [ ] **Step 2: Add the three new test functions**

Insert the following block immediately after the existing `test_build_acp_section_uses_explicit_app_config_without_global_config` function (after line 189, before the next function):

```python
def test_build_acp_section_contains_pi_routing_guidance_when_configured():
    explicit_config = SimpleNamespace(acp_agents={"pi": object()})
    section = prompt_module._build_acp_section(app_config=explicit_config)
    # Existing baseline assertions
    assert "ACP Agent Tasks" in section
    assert "/mnt/acp-workspace/" in section
    # New: routing guidance explicitly mentions "pi" and "small code tasks"
    assert "pi" in section
    assert "small" in section
    assert "code" in section
    # New: routing guidance includes the ACP agent name in the prefer-when instruction
    assert 'agent="pi"' in section or "agent='pi'" in section


def test_build_acp_section_no_pi_routing_when_pi_absent():
    explicit_config = SimpleNamespace(acp_agents={"codex": object()})
    section = prompt_module._build_acp_section(app_config=explicit_config)
    # Section still renders normally
    assert "ACP Agent Tasks" in section
    # But no "prefer pi" routing instruction should appear
    assert 'agent="pi"' not in section
    assert "agent='pi'" not in section


def test_build_acp_section_includes_fallback_to_inprocess_tools():
    explicit_config = SimpleNamespace(acp_agents={"codex": object()})
    section = prompt_module._build_acp_section(app_config=explicit_config)
    # Fallback line should mention the in-process tools by name
    assert "str_replace" in section
    assert "write_file" in section
    assert "bash" in section
```

- [ ] **Step 3: Update the existing test to also assert fallback presence**

In the same file, locate the existing `test_build_acp_section_uses_explicit_app_config_without_global_config` (line 178). Add one new assertion at the end of the function body (after the existing two `assert` lines):

```python
def test_build_acp_section_uses_explicit_app_config_without_global_config(monkeypatch):
    explicit_config = SimpleNamespace(acp_agents={"codex": object()})

    def fail_get_acp_agents():
        raise AssertionError("ambient get_acp_agents() must not be used when app_config is explicit")

    monkeypatch.setattr("deerflow.config.acp_config.get_acp_agents", fail_get_acp_agents)

    section = prompt_module._build_acp_section(app_config=explicit_config)

    assert "ACP Agent Tasks" in section
    assert "/mnt/acp-workspace/" in section
    # New: fallback hint is also present when an explicit (non-pi) agent is configured
    assert "str_replace" in section
```

- [ ] **Step 4: Run the new tests to verify they FAIL**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_lead_agent_prompt.py -v -k "test_build_acp_section_contains_pi_routing_guidance_when_configured or test_build_acp_section_no_pi_routing_when_pi_absent or test_build_acp_section_includes_fallback_to_inprocess_tools or test_build_acp_section_uses_explicit_app_config_without_global_config"`

Expected: 4 tests collected; the 3 new tests + the updated existing test all FAIL. Specifically:
- `test_build_acp_section_contains_pi_routing_guidance_when_configured` — FAIL (current implementation does not emit pi routing)
- `test_build_acp_section_no_pi_routing_when_pi_absent` — PASS (current implementation does not emit pi routing when pi is absent, so this test passes by accident; the negative assertion is the contract)
- `test_build_acp_section_includes_fallback_to_inprocess_tools` — FAIL (current implementation does not mention `str_replace`)
- `test_build_acp_section_uses_explicit_app_config_without_global_config` (updated) — FAIL (new `str_replace` assertion fails)

If `test_build_acp_section_no_pi_routing_when_pi_absent` passes already, that's the desired negative contract — leave it as a regression guard.

- [ ] **Step 5: Commit the failing tests (RED)**

```bash
git add backend/tests/test_lead_agent_prompt.py
git commit -m "test(prompt): add failing tests for pi routing guidance in _build_acp_section

TDD: write the contract first, then implement. Three new tests + one
extended test pin the routing-guidance contract and the in-process
fallback contract for the upcoming prompt change."
```

---

## Task 2: Implement `_build_acp_section` change to make tests pass

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` (replace the `_build_acp_section` function body, lines 717–738)

- [ ] **Step 1: Read the current `_build_acp_section` implementation**

Open `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` and read lines 717–738. The current function returns a static string when agents are configured, and `""` otherwise.

- [ ] **Step 2: Replace the function body**

Replace the entire body of `_build_acp_section` (the `return` statement and the function header is unchanged) with:

```python
def _build_acp_section(*, app_config: AppConfig | None = None) -> str:
    """Build the ACP agent prompt section, only if ACP agents are configured."""
    if app_config is None:
        try:
            from deerflow.config.acp_config import get_acp_agents

            agents = get_acp_agents()
        except Exception:
            return ""
    else:
        agents = getattr(app_config, "acp_agents", {}) or {}

    if not agents:
        return ""

    # Per-agent routing guidance: highlight `pi` as the preferred agent for
    # small, single-shot code-generation tasks. Other agents (codex, claude_code)
    # are still available, but the prompt steers the lead agent toward pi for
    # the "small code task" use case.
    routing_lines: list[str] = []
    for name in agents:
        if name == "pi":
            routing_lines.append(
                f"- **`{name}` (preferred for small code tasks)**: if the request is a small, "
                f"single-shot code-generation task (single-file edit, bug fix, small refactor), "
                f"prefer `invoke_acp_agent(agent=\"{name}\", prompt=...)` over in-process "
                f"`str_replace` / `write_file` / `bash` tools. {name} produces better diffs and "
                f"file-aware edits for that scope."
            )

    routing_section = ("\n" + "\n".join(routing_lines)) if routing_lines else ""

    return (
        "\n**ACP Agent Tasks (invoke_acp_agent):**\n"
        "- ACP agents (e.g. codex, claude_code) run in their own independent workspace — NOT in `/mnt/user-data/`\n"
        "- When writing prompts for ACP agents, describe the task only — do NOT reference `/mnt/user-data` paths\n"
        "- ACP agent results are accessible at `/mnt/acp-workspace/` (read-only) — use `ls`, `read_file`, or `bash cp` to retrieve output files\n"
        "- To deliver ACP output to the user: copy from `/mnt/acp-workspace/<file>` to `/mnt/user-data/outputs/<file>`, then use `present_files`"
        + routing_section
        + "\n- If an ACP agent returns an error (binary not installed, subprocess crash, timeout, etc.), fall back to in-process `str_replace` / `write_file` / `bash` tools"
    )
```

The function signature (def line, parameter list, return type annotation) is unchanged. Only the body is replaced.

- [ ] **Step 3: Run the four target tests to verify they PASS**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_lead_agent_prompt.py -v -k "test_build_acp_section_contains_pi_routing_guidance_when_configured or test_build_acp_section_no_pi_routing_when_pi_absent or test_build_acp_section_includes_fallback_to_inprocess_tools or test_build_acp_section_uses_explicit_app_config_without_global_config"`

Expected: all 4 tests PASS.

- [ ] **Step 4: Run the full lead-agent prompt test file to check for regressions**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_lead_agent_prompt.py -v`

Expected: all tests in `test_lead_agent_prompt.py` PASS. No regressions in the other prompt tests (subagent section, skills section, etc.).

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ -x -q`

Expected: all tests PASS. If any test fails, investigate and fix the prompt change (do not modify other tests to accommodate the new prompt content).

- [ ] **Step 6: Commit (GREEN)**

```bash
git add backend/packages/harness/deerflow/agents/lead_agent/prompt.py
git commit -m "feat(prompt): route small code tasks to pi; add in-process fallback hint

Extend _build_acp_section in the lead-agent system prompt with two new
behaviors:

1. When a 'pi' agent is configured, emit a per-agent routing line that
   instructs the lead agent to prefer invoke_acp_agent(agent='pi', ...)
   for small single-shot code-generation tasks (single-file edits, bug
   fixes, small refactors) over in-process str_replace / write_file /
   bash tools.

2. Always append a fallback note: if an ACP agent returns an error
   (binary missing, crash, timeout), fall back to the in-process tools.

The change is purely additive when 'pi' is configured, and otherwise
adds only the fallback hint. The existing baseline assertions (ACP
Agent Tasks header, /mnt/acp-workspace/ mention) are preserved."
```

---

## Task 3: Add `acp_agents.pi` block to `config.example.yaml` and bump `config_version`

**Files:**
- Modify: `config.example.yaml` (line 18 — bump `config_version`; lines 747–756 — append a new commented `pi` block after the `codex` block)

- [ ] **Step 1: Bump `config_version` from 10 to 11**

Open `config.example.yaml`. Locate line 18:

```yaml
config_version: 10
```

Change to:

```yaml
config_version: 11
```

This is the project convention: bumping `config_version` triggers `make config-upgrade` to merge new fields into the user's `config.yaml`.

- [ ] **Step 2: Append the `pi` block to the commented `acp_agents` example**

Locate the `acp_agents` commented example block (lines 735–756). The `codex` block ends at line 756. Insert a new `pi` block after the `codex` block (before the blank line that precedes the `# =====` separator for "Skills Configuration" at line 758):

```yaml
#   pi:
#     # Pi is a lightweight coding agent. For offline deployments, install via
#     # scripts/bundle-pi-coding-agent.sh and scripts/bundle-pi-acp.sh, which
#     # vendor the binaries to /usr/local/bin. For online use, `npx -y pi-acp`
#     # also works (requires npm registry access).
#     command: pi-acp
#     args: []
#     description: Pi coding agent — light, fast for small code-generation tasks (single-file edits, bug fixes, small refactors)
#     model: null
#     # auto_approve_permissions: false  # Set to true to auto-approve ACP permission requests
#     # env:                             # Optional: inject environment variables into the agent subprocess
#     #   PI_ACP_ENABLE_EMBEDDED_CONTEXT: "true"  # pi-acp-specific knob
```

The result is that the `acp_agents` example block (still entirely commented out) shows three example agents: `claude_code`, `codex`, and `pi`. Users uncomment the agents they want.

- [ ] **Step 3: Verify the YAML is still valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('config.example.yaml'))"`

Expected: exit 0, no output. (No syntax error.)

- [ ] **Step 4: Commit**

```bash
git add config.example.yaml
git commit -m "chore(config): add acp_agents.pi example block; bump config_version to 11

The new commented `pi` block under acp_agents: gives users a working
template for the lightweight pi coding agent. command is `pi-acp` for
offline bundle use; users on npm-registry-enabled networks may swap
in `command: npx, args: ['-y', 'pi-acp']`.

config_version bumped 10 -> 11 so make config-upgrade merges the new
field for users on older config.yaml."
```

---

## Task 4: Create `scripts/bundle-pi-coding-agent.sh`

**Files:**
- Create: `scripts/bundle-pi-coding-agent.sh`

- [ ] **Step 1: Write the script**

Create `scripts/bundle-pi-coding-agent.sh` with the following content (executable Bash script; mirrors `scripts/bundle-claude-code.sh`):

```bash
#!/bin/bash
# 在 Linux x86_64 (glibc) 机器上跑一次，把 @earendil-works/pi-coding-agent
# 装到临时 staging prefix，再打成 tarball 一次性 vendor 进镜像。
#
# 产物：offline-claude/pi-coding-agent-bundled-${VERSION}-linux-x64.tar.gz
#
# 用法：./scripts/bundle-pi-coding-agent.sh [版本号]
# 默认版本：0.78.1
#
# 重要：本脚本产生的 tarball 内嵌 native/WASM binary，**host = 目标平台**。
# 镜像本身是 linux/amd64，必须在 Linux x86_64 主机上跑。
# macOS / Windows / Linux arm64 / Alpine 都会产出不能用的 binary。
#
# 关于依赖：pi-agent-core / pi-ai / pi-tui / photon-node / 等都是 pi-coding-agent
# 的 transitive dependencies。一次 `npm install -g @earendil-works/pi-coding-agent`
# 会把整条依赖树装到 staging 下的 lib/node_modules/。不需要单装那几个包。
#
# 关于 install scripts：pi-coding-agent 本身以及整条依赖链的 hasInstallScript
# 都为 None，因此本脚本不加 --ignore-scripts（与 bundle-claude-code.sh 风格一致；
# 加了也无害，但会与现有脚本不一致）。
set -euo pipefail

VERSION="${1:-0.78.1}"
PLATFORM="linux-x64"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/offline-claude"
STAGING="$(mktemp -d)"

mkdir -p "$OUT_DIR"

# --- preflight: confirm host is Linux x86_64 ---
HOST_OS="$(uname -s)"
HOST_ARCH="$(uname -m)"
if [ "$HOST_OS" != "Linux" ] || [ "$HOST_ARCH" != "x86_64" ]; then
    echo "✗ ERROR: this script must run on Linux x86_64 (glibc)." >&2
    echo "  detected: ${HOST_OS} ${HOST_ARCH}" >&2
    echo "  the tarball embeds platform-specific assets and is NOT portable." >&2
    exit 1
fi

echo "==> Installing @earendil-works/pi-coding-agent@${VERSION} into staging prefix..."
npm install --prefix "$STAGING" -g @earendil-works/pi-coding-agent@"${VERSION}" 2>&1 | tail -20

# 校验 bin 存在
BIN_PATH="$STAGING/bin/pi"
if [ ! -x "$BIN_PATH" ]; then
    echo "    ✗ MISSING: $BIN_PATH" >&2
    ls -la "$STAGING/bin/" 2>/dev/null || true
    exit 1
fi
echo "    ✓ binary present: $BIN_PATH"

# 校验版本
PKG_JSON="$STAGING/lib/node_modules/@earendil-works/pi-coding-agent/package.json"
INSTALLED_VERSION="$(node -e "console.log(require('$PKG_JSON').version)")"
if [ "$INSTALLED_VERSION" != "$VERSION" ]; then
    echo "    ✗ version mismatch: requested=${VERSION}, installed=${INSTALLED_VERSION}" >&2
    exit 1
fi
echo "    ✓ version=${INSTALLED_VERSION}"

echo "==> Bundling staging directory..."
TARBALL="$OUT_DIR/pi-coding-agent-bundled-${VERSION}-${PLATFORM}.tar.gz"
tar -czf "$TARBALL" -C "$STAGING" .
rm -rf "$STAGING"

echo ""
echo "Done!"
ls -lh "$TARBALL"
echo "  sha256: $(shasum -a 256 "$TARBALL" | awk '{print $1}')"

echo ""
echo "Top-level packages in bundled tarball:"
tar -tzf "$TARBALL" \
  | grep -oE 'lib/node_modules/(@[^/]+/[^/]+|[^@/][^/]*)/' \
  | sed 's|lib/node_modules/||; s|/$||' \
  | sort -u
```

- [ ] **Step 2: Make the script executable**

Run: `chmod +x scripts/bundle-pi-coding-agent.sh`

- [ ] **Step 3: Syntax check the script**

Run: `bash -n scripts/bundle-pi-coding-agent.sh`

Expected: exit 0, no output.

- [ ] **Step 4: (Manual, not in CI) Verify on Linux x86_64**

On a Linux x86_64 host (e.g., a Debian/Ubuntu VM, or a Linux x86_64 Docker container), run:

```bash
./scripts/bundle-pi-coding-agent.sh 0.78.1
```

Expected: the script runs to completion, prints the tarball path, and produces `offline-claude/pi-coding-agent-bundled-0.78.1-linux-x64.tar.gz`. Then verify:

```bash
ls -lh offline-claude/pi-coding-agent-bundled-0.78.1-linux-x64.tar.gz
tar -tzf offline-claude/pi-coding-agent-bundled-0.78.1-linux-x64.tar.gz | grep -E 'bin/pi$|lib/node_modules/@earendil-works/pi-coding-agent/package.json$'
```

Expected: `bin/pi` and the package's `package.json` appear in the listing.

If you are on macOS / Windows / Linux arm64 / Alpine, this manual step is **skipped** — the host-guard aborts cleanly with a clear error.

- [ ] **Step 5: Commit**

```bash
git add scripts/bundle-pi-coding-agent.sh
git commit -m "chore(bundle): add bundle-pi-coding-agent.sh for offline x86_64 distribution

Mirrors scripts/bundle-claude-code.sh. Hard Linux x86_64 host guard.
Produces offline-claude/pi-coding-agent-bundled-${VERSION}-linux-x64.tar.gz.

The bundled tarball embeds pi and its transitive deps
(@earendil-works/pi-{agent-core,ai,tui}, @silvia-odwyer/photon-node,
@earendil-works/pi-coding-agent itself, etc.) under lib/node_modules/.
No need to bundle the deps separately — npm install -g pulls the
whole tree in one shot."
```

---

## Task 5: Create `scripts/bundle-pi-acp.sh`

**Files:**
- Create: `scripts/bundle-pi-acp.sh`

- [ ] **Step 1: Write the script**

Create `scripts/bundle-pi-acp.sh` with the following content (executable Bash script; mirrors `scripts/bundle-claude-agent-acp.sh`):

```bash
#!/bin/bash
# 任何带 node/npm + 网络的机器上跑（macOS / Linux 任意 arch 都行）。
# pi-acp 是纯 JS 适配器（无 native binary），跨平台，suffix 仅为命名一致。
#
# 产物：offline-claude/pi-acp-bundled-${VERSION}-linux-x64.tar.gz
# 用法：./scripts/bundle-pi-acp.sh [版本号]
# 默认版本：0.0.27
set -euo pipefail

VERSION="${1:-0.0.27}"
PLATFORM_SUFFIX="linux-x64"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/offline-claude"
STAGING="$(mktemp -d)"

mkdir -p "$OUT_DIR"

echo "==> Installing pi-acp@${VERSION} into staging prefix..."
npm install --prefix "$STAGING" -g pi-acp@"${VERSION}" 2>&1 | tail -20

BIN_PATH="$STAGING/bin/pi-acp"
if [ ! -x "$BIN_PATH" ]; then
    echo "    ✗ MISSING: $BIN_PATH" >&2
    ls -la "$STAGING/bin/" 2>/dev/null || true
    exit 1
fi
echo "    ✓ binary present: $BIN_PATH"

PKG_JSON="$STAGING/lib/node_modules/pi-acp/package.json"
INSTALLED_VERSION="$(node -e "console.log(require('$PKG_JSON').version)")"
if [ "$INSTALLED_VERSION" != "$VERSION" ]; then
    echo "    ✗ version mismatch: requested=${VERSION}, installed=${INSTALLED_VERSION}" >&2
    exit 1
fi
echo "    ✓ version=${INSTALLED_VERSION}"

echo "==> Bundling staging directory..."
TARBALL="$OUT_DIR/pi-acp-bundled-${VERSION}-${PLATFORM_SUFFIX}.tar.gz"
tar -czf "$TARBALL" -C "$STAGING" .
rm -rf "$STAGING"

echo ""
echo "Done!"
ls -lh "$TARBALL"
echo "  sha256: $(shasum -a 256 "$TARBALL" | awk '{print $1}')"

echo ""
echo "Binaries in bundled tarball:"
tar -tzf "$TARBALL" | grep -E '^bin/' | sort
```

- [ ] **Step 2: Make the script executable**

Run: `chmod +x scripts/bundle-pi-acp.sh`

- [ ] **Step 3: Syntax check the script**

Run: `bash -n scripts/bundle-pi-acp.sh`

Expected: exit 0, no output.

- [ ] **Step 4: (Manual, not in CI) Verify on any node host**

On any host with `node` and `npm`, run:

```bash
./scripts/bundle-pi-acp.sh 0.0.27
```

Expected: the script runs to completion on any host (no x86 guard), produces `offline-claude/pi-acp-bundled-0.0.27-linux-x64.tar.gz`. This script is intentionally host-agnostic because `pi-acp` is pure JS.

- [ ] **Step 5: Commit**

```bash
git add scripts/bundle-pi-acp.sh
git commit -m "chore(bundle): add bundle-pi-acp.sh for offline ACP adapter distribution

Mirrors scripts/bundle-claude-agent-acp.sh. No host guard — pi-acp is
pure JS (only deps are @agentclientprotocol/sdk and zod), so the
tarball is portable across macOS / Linux / Windows / any arch.

Suffix `-linux-x64` is retained for naming consistency with other
bundles; the tarball is cross-platform."
```

---

## Task 6: Create `scripts/bundle-pi-web.sh`

**Files:**
- Create: `scripts/bundle-pi-web.sh`

- [ ] **Step 1: Write the script**

Create `scripts/bundle-pi-web.sh` with the following content (executable Bash script; mirrors `scripts/bundle-pi-coding-agent.sh` because of the sharp transitive dep):

```bash
#!/bin/bash
# 在 Linux x86_64 (glibc) 机器上跑一次，把 @agegr/pi-web 装到临时 staging prefix，
# 再打成 tarball 供离线部署使用。
#
# 产物：offline-claude/pi-web-bundled-${VERSION}-linux-x64.tar.gz
#
# 用法：./scripts/bundle-pi-web.sh [版本号]
# 默认版本：0.6.13
#
# 重要：本脚本产生的 tarball **不进** DeerFlow 镜像。pi-web 是 pi 项目的独立
# Web UI，与 DeerFlow 项目无联动；本脚本仅为方便用户离线部署 pi-web 而存在。
# 跑完把 tarball 拿到目标机器上：tar -xzf pi-web-bundled-...-linux-x64.tar.gz -C /opt
# 然后 /opt/bin/pi-web 即可启动。
#
# x86 guard：虽然 pi-web 本身是纯 JS，但它的 next 依赖通过 optionalDependencies
# 拉入 sharp（含 platform-specific native binary）。必须在 Linux x86_64 主机上跑
# 才能产生与目标平台一致的 tarball。
set -euo pipefail

VERSION="${1:-0.6.13}"
PLATFORM="linux-x64"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/offline-claude"
STAGING="$(mktemp -d)"

mkdir -p "$OUT_DIR"

# --- preflight: confirm host is Linux x86_64 ---
HOST_OS="$(uname -s)"
HOST_ARCH="$(uname -m)"
if [ "$HOST_OS" != "Linux" ] || [ "$HOST_ARCH" != "x86_64" ]; then
    echo "✗ ERROR: this script must run on Linux x86_64 (glibc)." >&2
    echo "  detected: ${HOST_OS} ${HOST_ARCH}" >&2
    echo "  pi-web transitively pulls in sharp (native image library)," >&2
    echo "  whose prebuilt binary is platform-specific." >&2
    exit 1
fi

echo "==> Installing @agegr/pi-web@${VERSION} into staging prefix..."
npm install --prefix "$STAGING" -g @agegr/pi-web@"${VERSION}" 2>&1 | tail -20

BIN_PATH="$STAGING/bin/pi-web"
if [ ! -x "$BIN_PATH" ]; then
    echo "    ✗ MISSING: $BIN_PATH" >&2
    ls -la "$STAGING/bin/" 2>/dev/null || true
    exit 1
fi
echo "    ✓ binary present: $BIN_PATH"

PKG_JSON="$STAGING/lib/node_modules/@agegr/pi-web/package.json"
INSTALLED_VERSION="$(node -e "console.log(require('$PKG_JSON').version)")"
if [ "$INSTALLED_VERSION" != "$VERSION" ]; then
    echo "    ✗ version mismatch: requested=${VERSION}, installed=${INSTALLED_VERSION}" >&2
    exit 1
fi
echo "    ✓ version=${INSTALLED_VERSION}"

echo "==> Bundling staging directory..."
TARBALL="$OUT_DIR/pi-web-bundled-${VERSION}-${PLATFORM}.tar.gz"
tar -czf "$TARBALL" -C "$STAGING" .
rm -rf "$STAGING"

echo ""
echo "Done!"
ls -lh "$TARBALL"
echo "  sha256: $(shasum -a 256 "$TARBALL" | awk '{print $1}')"

echo ""
echo "Top-level packages in bundled tarball:"
tar -tzf "$TARBALL" \
  | grep -oE 'lib/node_modules/(@[^/]+/[^/]+|[^@/][^/]*)/' \
  | sed 's|lib/node_modules/||; s|/$||' \
  | sort -u
```

- [ ] **Step 2: Make the script executable**

Run: `chmod +x scripts/bundle-pi-web.sh`

- [ ] **Step 3: Syntax check the script**

Run: `bash -n scripts/bundle-pi-web.sh`

Expected: exit 0, no output.

- [ ] **Step 4: (Manual, not in CI) Verify on Linux x86_64**

On a Linux x86_64 host, run:

```bash
./scripts/bundle-pi-web.sh 0.6.13
```

Expected: the script runs to completion, prints the tarball path, and produces `offline-claude/pi-web-bundled-0.6.13-linux-x64.tar.gz`. (Note: this tarball is large — it includes Next.js, React, and pi-coding-agent as transitive deps.)

If you are on macOS / Windows / Linux arm64, this step is skipped.

- [ ] **Step 5: Commit**

```bash
git add scripts/bundle-pi-web.sh
git commit -m "chore(bundle): add bundle-pi-web.sh for offline standalone Web UI

Mirrors bundle-pi-coding-agent.sh (x86 host guard) because pi-web
transitively pulls sharp via next (a native image library). The
tarball is NOT wired into the DeerFlow image — pi-web is a
standalone Web UI for the pi coding agent, separate from DeerFlow.
This script is for users who want to vendor pi-web for offline
deployment on the same offline/host-restricted networks as DeerFlow."
```

---

## Task 7: Add commented-out `pi-coding-agent` and `pi-acp` install blocks to `backend/Dockerfile`

**Files:**
- Modify: `backend/Dockerfile` (builder stage around line 113–121; runtime stage around line 204–212)

- [ ] **Step 1: Read the current state of `backend/Dockerfile`**

Open `backend/Dockerfile`. The file has two stages:
- **Builder stage** (around lines 95–125): copies Node.js from `node:22-bookworm`, installs Claude Code CLI bundle and Claude Agent ACP bundle (active install).
- **Runtime stage** (around lines 180–212): copies Node.js from builder, has the Claude Code CLI install active, and the Claude Agent ACP install commented out (after commit 621626a8).

For each stage, you'll add a **commented-out** block for `pi-coding-agent` + `pi-acp` right after the corresponding claude blocks. Default state is commented — the user opts in by uncommenting.

- [ ] **Step 2: Add the commented-out `pi` block in the builder stage**

In the builder stage, locate the active `claude-agent-acp` install block (ends around line 121). Insert the following block immediately after it (after the `node -e "console.log(...)"` line, before the `EXPOSE` line):

```dockerfile
# ── Install Pi Coding Agent (offline bundled, opt-in) ─────────────────────
# pi-acp 在 stdio 通信时 shell out 调 `pi --mode rpc`，所以 acp_agents.pi
# 需要两个 bundle 同时 vendor：
#   1. @earendil-works/pi-coding-agent  (pi 二进制本身)
#   2. pi-acp                           (DeerFlow 调起的 ACP 适配器)
# 启用：uncomment 下面 + 把对应 tarball 放到 offline-claude/。
# 关闭（默认）：保持 commented，不影响镜像构建。
#
# 产物路径：
#   scripts/bundle-pi-coding-agent.sh → offline-claude/pi-coding-agent-bundled-${VERSION}-linux-x64.tar.gz
#   scripts/bundle-pi-acp.sh          → offline-claude/pi-acp-bundled-${VERSION}-linux-x64.tar.gz
# 两者都在 Linux x86_64 runner 上执行。
# pi-web **不** vendor 进镜像，它是独立 Web UI，与 DeerFlow 无联动。
# ARG PI_CODING_AGENT_VERSION=0.78.1
# ARG PI_ACP_VERSION=0.0.27
# COPY offline-claude/pi-coding-agent-bundled-${PI_CODING_AGENT_VERSION}-linux-x64.tar.gz /tmp/pi-agent-bundle.tar.gz
# RUN tar -xzf /tmp/pi-agent-bundle.tar.gz -C /usr/local --no-same-owner \
#     && rm /tmp/pi-agent-bundle.tar.gz \
#     && pi --version
# 
# COPY offline-claude/pi-acp-bundled-${PI_ACP_VERSION}-linux-x64.tar.gz /tmp/pi-acp-bundle.tar.gz
# RUN tar -xzf /tmp/pi-acp-bundle.tar.gz -C /usr/local --no-same-owner \
#     && rm /tmp/pi-acp-bundle.tar.gz \
#     && test -x /usr/local/bin/pi-acp
```

- [ ] **Step 3: Add the same commented-out `pi` block in the runtime stage**

In the runtime stage, locate the commented-out `claude-agent-acp` install block (around lines 204–212, after commit 621626a8 it's now commented). Insert the same pi block immediately after it (the same content as Step 2, byte-for-byte).

The two stages will then have parallel structure:
- Builder: claude-code (active) + claude-agent-acp (active) + pi-coding-agent (commented) + pi-acp (commented)
- Runtime: claude-code (active) + claude-agent-acp (commented) + pi-coding-agent (commented) + pi-acp (commented)

- [ ] **Step 4: Verify the Dockerfile is still syntactically valid**

The Dockerfile's syntax can be lightly checked by `docker run --rm -i hadolint/hadolint < Dockerfile` if `hadolint` is available. Without hadolint, eyeball the result: comments and the active install blocks should all be properly terminated with newlines, and the uncommented lines should form a coherent Dockerfile.

- [ ] **Step 5: Commit**

```bash
git add backend/Dockerfile
git commit -m "chore(dockerfile): add commented-out pi-coding-agent + pi-acp install blocks

Mirrors the existing commented-out claude-agent-acp block. Default
state: commented. Users who want pi in the runtime image uncomment
both the pi-coding-agent and pi-acp sections and drop the
corresponding tarballs into offline-claude/.

pi-web is NOT added to the Dockerfile — it's a standalone Web UI
separate from DeerFlow."
```

---

## Task 8: Update `backend/CLAUDE.md` to mention `pi`

**Files:**
- Modify: `backend/CLAUDE.md` (line 296 — the "ACP agent tools" section)

- [ ] **Step 1: Read the current "ACP agent tools" section**

Open `backend/CLAUDE.md`. Read lines 296–300. The section lists the ACP agent tool and its key behaviors. Currently it doesn't mention `pi` (since `pi` is a new addition).

- [ ] **Step 2: Add a `pi` line and a brief routing note**

Insert the following two bullets at the end of the "ACP agent tools" section (after the existing bullets, before the next `###` heading "### MCP System" at line 303):

```markdown
- `pi` is a recommended ACP agent for the **lightweight code-generation fast path**. When configured, the lead-agent system prompt instructs the model to prefer `invoke_acp_agent(agent="pi", ...)` for small single-shot code tasks (single-file edits, bug fixes, small refactors) over in-process `str_replace`/`write_file`/`bash` tools. The `pi` agent uses the [pi-acp](https://github.com/svkozak/pi-acp) ACP adapter (vendored via `scripts/bundle-pi-coding-agent.sh` and `scripts/bundle-pi-acp.sh` for offline use).
- See `docx/superpowers/specs/2026-06-06-pi-acp-integration-design.md` for the design rationale and `docs/PI_ACP.md` for user-facing setup instructions.
```

- [ ] **Step 3: Verify the section still reads coherently**

Scroll up and down to confirm the section is well-formed Markdown. The new bullets should fit naturally after the existing ones.

- [ ] **Step 4: Commit**

```bash
git add backend/CLAUDE.md
git commit -m "docs(backend): mention pi as a recommended ACP agent in CLAUDE.md

Adds a brief routing description to the existing ACP agent tools
section, pointing to the spec and the user-facing PI_ACP doc."
```

---

## Task 9: Create user-facing documentation `docs/PI_ACP.md`

**Files:**
- Create: `docs/PI_ACP.md`

- [ ] **Step 1: Write the doc**

Create `docs/PI_ACP.md` with the following content:

```markdown
# pi Coding Agent Integration

DeerFlow can route small, single-shot code-generation tasks to the [`pi`](https://github.com/earendil-works/pi) coding agent via the [`pi-acp`](https://github.com/svkozak/pi-acp) ACP adapter. The integration reuses the existing `invoke_acp_agent` tool path — no new code modules are introduced.

## What you get

- **Faster code edits**: pi is a lightweight agent focused on file-aware code generation with proper diffs.
- **Smaller prompts, smaller models**: pi-acp shells out to `pi --mode rpc`, so the lead agent doesn't have to think about file edit mechanics for simple cases.
- **Same isolation as `codex` / `claude_code`**: pi operates in a per-thread `acp-workspace`, accessible to the lead agent as read-only `/mnt/acp-workspace/`. User-visible artifacts are surfaced via the standard `cp` + `present_files` flow.

## When the lead agent routes to `pi`

The lead agent's system prompt is configured to prefer `invoke_acp_agent(agent="pi", ...)` for tasks that look like:

- Single-file edits ("fix the bug on line 47")
- Small refactors ("rename this function")
- Code generation from a short spec ("add a function `foo` that does X")

For multi-step tasks, research-heavy tasks, or tasks that need many tools, the lead agent continues to use its in-process tools and (optionally) subagents.

If the `pi` invocation fails (binary not installed, subprocess crash, timeout), the lead agent falls back to in-process `str_replace` / `write_file` / `bash` tools.

## Setup

### Online (npm registry accessible)

In your `config.yaml` (`make config-upgrade` after pulling the latest `config.example.yaml`):

```yaml
acp_agents:
  pi:
    command: npx
    args: ["-y", "pi-acp"]
    description: Pi coding agent for small code-generation tasks
    model: null
    auto_approve_permissions: true
    env: {}
```

Then make sure the upstream `pi` binary is available on `PATH` (see [pi's README](https://github.com/earendil-works/pi) for install instructions).

### Offline (LAN-restricted, no npm access)

Use the bundle scripts to vendor the binaries:

```bash
# On a Linux x86_64 host with npm + network:
./scripts/bundle-pi-coding-agent.sh
./scripts/bundle-pi-acp.sh

# Copy the resulting tarballs to your offline-claude/ directory:
#   offline-claude/pi-coding-agent-bundled-0.78.1-linux-x64.tar.gz
#   offline-claude/pi-acp-bundled-0.0.27-linux-x64.tar.gz
```

Then in your `config.yaml`:

```yaml
acp_agents:
  pi:
    command: pi-acp
    args: []
    description: Pi coding agent (offline bundle)
    model: null
    auto_approve_permissions: true
    env: {}
```

(`pi-acp` and `pi` are both at `/usr/local/bin/` once the Dockerfile's commented-out blocks are uncommented and the image is rebuilt with the tarballs in `offline-claude/`.)

## Limitations

- Routing is prompt-driven. The lead agent may not always choose `pi` — observe behavior in Langfuse and tune the prompt if needed.
- `pi` is a separate process with its own model configuration. You need a working `pi` install and its own API keys.
- pi is not currently used as a `subagent` (no background-thread delegation); it's only invoked through the `invoke_acp_agent` tool path.

## See also

- Design spec: `docx/superpowers/specs/2026-06-06-pi-acp-integration-design.md`
- General ACP docs: see the "ACP agent tools" section in `backend/CLAUDE.md`
- `pi-acp` upstream: <https://github.com/svkozak/pi-acp>
- `pi` upstream: <https://github.com/earendil-works/pi>
```

- [ ] **Step 2: Commit**

```bash
git add docs/PI_ACP.md
git commit -m "docs: add PI_ACP.md user-facing setup guide for pi integration

Covers online (npx) and offline (bundle scripts) install paths,
explains when the lead agent routes to pi, and documents known
limitations. Cross-references the design spec and the upstream
pi / pi-acp repos."
```

---

## Task 10: Final verification

**Files:** none (read-only checks)

- [ ] **Step 1: Run ruff lint on the backend**

Run: `cd backend && make lint`

Expected: exit 0, no lint errors. The new prompt code follows existing style (Pydantic / LangGraph / ruff conventions).

- [ ] **Step 2: Run the full backend test suite**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/ -q`

Expected: all tests PASS. The 4 ACP-prompt tests from Tasks 1–2 are part of this run.

- [ ] **Step 3: Run ruff format check (auto-fixes if needed)**

Run: `cd backend && uv run ruff format --check .`

Expected: no diff. If ruff wants to reformat something, run `uv run ruff format .` to apply, then re-run lint and tests.

- [ ] **Step 4: Verify the prompt change visually**

Read the updated `_build_acp_section` in `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`. Confirm:
- When agents are empty, the function returns `""` (no change to baseline behavior).
- When agents include `pi`, the routing line appears.
- The fallback line is always present when agents are non-empty.

- [ ] **Step 5: (Manual, on Linux x86_64 only) Smoke-test the bundle scripts**

Skip this step on macOS / Windows / Linux arm64.

On a Linux x86_64 host:

```bash
./scripts/bundle-pi-coding-agent.sh
./scripts/bundle-pi-acp.sh
./scripts/bundle-pi-web.sh
ls -lh offline-claude/pi-*-bundled-*-linux-x64.tar.gz
```

Expected: three tarballs are produced. The first two (~50–100 MB each) are the ACP-path bundles; the third (~hundreds of MB) is the standalone pi-web bundle.

- [ ] **Step 6: Verify the spec ↔ plan ↔ diff alignment**

Confirm the four pieces of work are present in the working tree:

```bash
git log --oneline -n 10
git diff main --stat
```

Expected: at least 6 commits (Tasks 1, 2, 3, 4, 5, 6, 7, 8, 9 — Tasks 1 & 2 each have a commit, Tasks 4–6 each have a commit, Tasks 3, 7, 8, 9 each have a commit; 9 total). The diff against `main` should show:
- 3 new files in `scripts/`
- 1 new file in `docs/`
- Modified `config.example.yaml`
- Modified `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`
- Modified `backend/tests/test_lead_agent_prompt.py`
- Modified `backend/Dockerfile`
- Modified `backend/CLAUDE.md`

---

## Done

When all 10 tasks are committed, the integration is ready. The spec, plan, and implementation are aligned. Push the branch and open a PR per the project's contribution guidelines.

---

## Self-Review Notes

- **Spec coverage:** every spec requirement (sections 3, 4, 5, 6, 7) maps to a task: prompt change → Task 2, tests → Task 1, config → Task 3, three bundle scripts → Tasks 4/5/6, Dockerfile → Task 7, CLAUDE.md → Task 8, user-facing doc → Task 9, final verification → Task 10. No gaps.
- **Placeholder scan:** every step has the actual content (exact code, exact commands, exact paths). No "TBD" / "TODO" / "similar to Task N".
- **Type consistency:** the prompt implementation iterates `for name in agents` (matches test expectations of `name` only, no `cfg` access). The function signature is unchanged. Test assertions match the strings emitted by the implementation.
