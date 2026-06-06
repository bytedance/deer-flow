# pi-acp Integration into DeerFlow

**Date**: 2026-06-06
**Status**: Design (awaiting user review)
**Scope**: Lightweight integration of `pi-acp` as a code-generation fast path + offline bundle scripts

---

## 1. Context and Motivation

The user wants `pi-acp` (ACP adapter for the `pi` coding agent) integrated into DeerFlow so that **small, single-shot code-generation tasks** can be delegated to `pi` directly. Stated motivations:

- pi is a **lightweight** coding agent (vs. DeerFlow's full lead-agent orchestration)
- Better **code quality** for small edits
- "**小任务直接走 pi**" — small tasks should bypass the heavyweight lead agent stack

Crucially, the user does **not** want a new runtime mode, new API route, or a backend classifier. The desired design is:

- Reuse DeerFlow's existing `invoke_acp_agent` tool path
- Configure `pi` as an ACP agent in `config.yaml`
- Guide the lead agent via system prompt to route small code tasks to `pi`
- Fall back to in-process tools (`str_replace`, `write_file`, `bash`) if `pi` is unavailable

A secondary goal: provide **offline x86_64 bundle scripts** (matching the existing `bundle-claude-code.sh` / `bundle-claude-agent-acp.sh` pattern) so deployments on offline / LAN-restricted networks can vendor `pi-coding-agent`, `pi-acp`, and the standalone `pi-web` Web UI.

`@agegr/pi-web` is included in the bundle work as a **standalone convenience** for the user, not wired into DeerFlow.

---

## 2. Architecture

```
┌─────────────────┐
│  Lead Agent     │
│  (DeerFlow)     │  System prompt: "small code tasks → prefer invoke_acp_agent(agent='pi')"
└────────┬────────┘
         │  recognizes code-generation intent
         ▼
┌─────────────────────┐
│ invoke_acp_agent    │  Built-in tool; existing impl
│ (tool)              │
└────────┬────────────┘
         │  agent="pi"  →  spawn_agent_process(pi-acp, cwd=acp_workspace_dir)
         ▼
┌─────────────────────┐
│   pi-acp 子进程     │  stdio JSON-RPC 2.0
│   (ACP 适配器)      │
└────────┬────────────┘
         │  shells out:  pi --mode rpc
         ▼
┌─────────────────────┐
│  pi 二进制          │  Coding agent
│  (pi-coding-agent)  │
└────────┬────────────┘
         │  writes to acp-workspace
         ▼
   /mnt/acp-workspace/   (read-only to lead agent)
   → cp to /mnt/user-data/outputs/
```

**Key invariants**:
- `pi` operates in `acp-workspace`, isolated from lead agent's user-data tree
- `acp-workspace` is read-only mounted to lead agent as `/mnt/acp-workspace/`
- Lead agent must `cp` outputs to `/mnt/user-data/outputs/` and use `present_files` to surface them
- `acp_agents.pi` config presence is the on/off switch; no new code required to disable

**No new code paths**: this design adds zero new modules to the `deerflow` package. All behavior is driven by:
1. `config.yaml`'s `acp_agents` section (data only)
2. The `_build_acp_section` prompt string (text only)

---

## 3. File Changes

| File | Change | Risk |
|------|--------|------|
| `config.example.yaml` (~L735) | Add commented-out `pi` block under `acp_agents:`; bump `config_version` so `make config-upgrade` merges the new field | very low (template) |
| `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` (`_build_acp_section`, L717) | Extend ACP section with: (a) "if a 'pi' agent is configured, prefer it for small single-shot code tasks" (b) "if ACP returns an error, fall back to in-process `str_replace`/`write_file`/`bash`" | low (text only) |
| `backend/tests/test_lead_agent_prompt.py` (L178 area) | Add 2 new tests + update 1 existing | very low |
| `backend/CLAUDE.md` (ACP section) | Mention `pi` as a recommended ACP agent for the code-gen fast path | very low (doc) |
| `docs/ACP_AGENTS.md` (or new `docs/PI_ACP.md`) | New section: "Routing small code tasks to `pi`" with sample session trace | very low (doc) |
| `scripts/bundle-pi-coding-agent.sh` | **NEW** — bundle `pi` agent binary (x86 host guard) | low |
| `scripts/bundle-pi-acp.sh` | **NEW** — bundle `pi-acp` adapter (no host guard) | low |
| `scripts/bundle-pi-web.sh` | **NEW** — bundle `pi-web` standalone (x86 host guard; **not** wired into Dockerfile) | low |
| `backend/Dockerfile` (builder L98-121, runtime L189-212) | Add commented-out blocks for `pi-coding-agent` + `pi-acp` bundles (mirroring existing `claude-code` / `claude-agent-acp` pattern). `pi-web` is **not** added. | low (default commented) |

**Rollback cost**: every change is independently revertable. Worst case: revert one commit restores baseline.

---

## 4. Data Flow and Error Handling

### 4.1 Normal path

```
1. User:  "修复 utils.py 第 47 行的 bug"
2. Lead Agent (LLM): reads system prompt → identifies "small, single-file, pure code task"
3. Lead Agent calls:  invoke_acp_agent(agent="pi", prompt="修复 utils.py 第 47 行...")
4. invoke_acp_agent (existing code in `tools/builtins/invoke_acp_agent_tool.py`):
   - resolve thread_id from config
   - resolve acp_workspace_dir = {base_dir}/users/{user_id}/threads/{thread_id}/acp-workspace/
   - mkdir physical dir
   - spawn_agent_process(pi-acp, env=..., cwd=acp_workspace_dir)
   - conn.new_session(cwd=acp_workspace_dir, mcp_servers=[...])
   - conn.prompt(prompt=[text_block(...)])
   - _CollectingClient.session_update accumulates text chunks
5. pi-acp → pi (--mode rpc) → edits files inside acp-workspace
6. async with exits → result = client.collected_text
7. ToolMessage returns result to lead agent
8. Lead Agent calls bash: cp /mnt/acp-workspace/utils.py /mnt/user-data/outputs/utils.py
9. Lead Agent calls present_files to surface outputs to the user
```

### 4.2 Error paths

| Scenario | Existing behavior (already implemented) | Additional handling we add |
|----------|----------------------------------------|---------------------------|
| `pi-acp` / `pi` binary missing | `_format_invocation_error` returns "Command not found, install..." | Prompt adds fallback: "if ACP returns an error, use `str_replace`/`write_file`/`bash` instead" |
| pi process crash / timeout | Caught, error ToolMessage returned | Same — lead agent sees error, falls back per prompt |
| `pi` not configured in `config.yaml` | `invoke_acp_agent` tool not registered (`get_available_tools` skips) | `_build_acp_section` does not emit the "prefer pi" guidance (no false promises) |
| `pi` misconfigured (bad command) | `_format_invocation_error` friendly hint | Same as above |
| pi writes many files to acp-workspace | No LRU cleanup of acp-workspace (matches `claude_code`/`codex`) | Out of scope; future improvement |
| `ThreadDataMiddleware` did not build acp-workspace | `_get_work_dir` falls back to global `{base_dir}/acp-workspace/` | Existing fallback, no change needed |

### 4.3 Invariants (already enforced by `invoke_acp_agent`)

- `acp-workspace` is always pi's cwd, physically isolated from lead agent
- Read-only mounted at `/mnt/acp-workspace/` for lead agent to read output
- User-visible artifacts must be `cp`'d to `/mnt/user-data/outputs/` and surfaced via `present_files`
- Lead agent must not pass `/mnt/user-data` paths in the prompt to `pi` (prompt explicitly forbids)

---

## 5. Testing Strategy

### 5.1 New / modified tests

| Test | File | Assertion |
|------|------|-----------|
| `test_build_acp_section_contains_pi_routing_guidance_when_configured` | `tests/test_lead_agent_prompt.py` | When `acp_agents` contains `pi`, prompt section includes "prefer pi for small code tasks" wording |
| `test_build_acp_section_no_pi_routing_when_pi_absent` | same | When `acp_agents` only has `codex` (no `pi`), prompt section does **not** mention "pi" routing (avoids hallucination) |
| `test_build_acp_section_includes_fallback_to_inprocess_tools` | same | Prompt section includes the fallback note about `str_replace`/`write_file`/`bash` |
| Update `test_build_acp_section_uses_explicit_app_config_without_global_config` | same | Existing assertions preserved; add assertion for new guidance present |

### 5.2 Tests NOT added (already covered)

- `tests/test_invoke_acp_agent_tool.py` (18 cases) already covers spawn, env, per-thread workspace, MCP bridging, permission handling, missing binary
- E2E pi behavior is covered by pi-acp's own tests
- DeerFlow layer only needs to verify (1) config wiring and (2) prompt routing

### 5.3 Manual smoke test (developer flow)

```bash
# 1. Edit config.yaml to enable pi
#    Uncomment the `pi` block under `acp_agents:` (or use make config-upgrade)

# 2. Install pi binaries locally (user's responsibility)
npm install -g @earendil-works/pi-coding-agent
npm install -g pi-acp
export PI_ACP_ENABLE_EMBEDDED_CONTEXT=true  # optional

# 3. Start DeerFlow
make dev

# 4. Send: "把 utils.py 第 47 行的 try/except 加上"
#    Expected: lead agent calls invoke_acp_agent(agent="pi", ...).
#    Verify in Langfuse / trace: ACP session → npx spawn → returned text
```

### 5.4 Risk acknowledgement (not testable)

- Real pi behavior depends on user machine having `npx` + `pi` + `pi-acp` installed — out of DeerFlow control
- LLM prompt-following is not 100% reliable — this is a prompt-engineering question. Future strengthening (e.g., tool-call rewriting in `subagent_limit_middleware`) is **out of scope** for this spec.

---

## 6. Bundle Scripts (offline x86_64 distribution)

Three new scripts, all in `scripts/`, each producing a tarball into `offline-claude/`. The directory name `offline-claude/` is retained for compatibility (it already holds the two claude bundles); it will hold mixed tarballs going forward. **A directory rename to `offline-vendor/` is a separate refactor and out of scope.**

### 6.1 `scripts/bundle-pi-coding-agent.sh` (used by Dockerfile)

Mirrors `bundle-claude-code.sh`: x86_64 hard host guard, single `npm install -g`, tar to `offline-claude/pi-coding-agent-bundled-${VERSION}-linux-x64.tar.gz`.

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

### 6.2 `scripts/bundle-pi-acp.sh` (used by Dockerfile)

Mirrors `bundle-claude-agent-acp.sh`: no host guard, pure JS adapter. Output `offline-claude/pi-acp-bundled-${VERSION}-linux-x64.tar.gz`.

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

### 6.3 `scripts/bundle-pi-web.sh` (NOT used by Dockerfile)

Mirrors `bundle-pi-coding-agent.sh` style (x86 host guard) because `pi-web` transitively pulls `sharp` via `next` (platform-specific native binary). The script produces a tarball that the user extracts to `/opt` (or similar) on the target machine and runs `pi-web` manually. **This script does NOT contribute to the DeerFlow image.**

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

### 6.4 Dockerfile changes (only 6.1 + 6.2; 6.3 is NOT in Dockerfile)

In both `builder` and `runtime` stages, add a commented-out block mirroring the existing `claude-code` / `claude-agent-acp` pattern. Default state: commented, so the image is unaffected unless the user opts in.

```dockerfile
# ── Install Pi Coding Agent (offline bundled) ─────────────────────────────
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

### 6.5 `config.example.yaml` addition

```yaml
acp_agents:
  pi:
    # 离线场景：command 直接用 `pi-acp`（bundle 已 vendor 到 /usr/local/bin/）
    # 在线场景：可用 `npx -y pi-acp`，但需保证 npm 源可达
    command: pi-acp
    args: []
    description: Pi coding agent — light, fast for small code-generation tasks (single-file edits, bug fixes, small refactors)
    model: null  # 可选：覆盖 pi 的默认模型
    auto_approve_permissions: true
    env: {}  # 可选：例如 PI_ACP_ENABLE_EMBEDDED_CONTEXT: "true"
```

Also bump `config_version` in `config.example.yaml` so `make config-upgrade` will merge the new field for users on older config.yaml.

---

## 7. `prompt.py` change details

Current `_build_acp_section` (line 717–738 of `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`):

```python
return (
    "\n**ACP Agent Tasks (invoke_acp_agent):**\n"
    "- ACP agents (e.g. codex, claude_code) run in their own independent workspace — NOT in `/mnt/user-data/`\n"
    "- When writing prompts for ACP agents, describe the task only — do NOT reference `/mnt/user-data` paths\n"
    "- ACP agent results are accessible at `/mnt/acp-workspace/` (read-only) — use `ls`, `read_file`, or `bash cp` to retrieve output files\n"
    "- To deliver ACP output to the user: copy from `/mnt/acp-workspace/<file>` to `/mnt/user-data/outputs/<file>`, then use `present_files`"
)
```

**Proposed change** (extend the section to include routing guidance and fallback):

```python
# Build per-agent routing hints for ACP entries that should be preferred.
routing_lines: list[str] = []
for name, cfg in agents.items():
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
    + (
        "\n- If an ACP agent returns an error (binary not installed, subprocess crash, "
        "timeout, etc.), fall back to in-process `str_replace` / `write_file` / `bash` tools"
        if agents else ""
    )
)
```

When no agents are configured, the section is omitted entirely (existing behavior preserved).

---

## 8. Risks and Open Questions

### Risks

1. **LLM prompt adherence**: lead agent may not always route small code tasks to `pi`. Mitigation: prompt is a hint, not a contract. User can observe behavior in Langfuse and iterate on the prompt.
2. **Offline build host assumption**: bundle scripts require Linux x86_64 with glibc. Users on macOS/Windows must use a Linux x86_64 runner (CI, container, or VM).
3. **Image bloat**: pi-coding-agent + deps add ~50-100 MB to the image when uncommented. Acceptable for opt-in feature.
4. **pi-web is large**: `pi-web` bundle includes Next.js + React + sharp. Tarball is several hundred MB. Mitigated by **not** putting it in the DeerFlow image.
5. **Directory naming**: `offline-claude/` is now misleading (holds mixed claude + pi tarballs). Renaming to `offline-vendor/` is a separate refactor — out of scope.

### Out of scope (explicitly)

- Backend LLM classifier for code-task routing
- Fast-path API routes (`POST /api/pi/quick` etc.)
- Adding `pi` as a subagent (vs. ACP tool)
- Renaming `offline-claude/` directory
- Custom UI button for "quick code" in the frontend
- Auto-update mechanism for the bundled binaries

### Open questions

- None blocking. The user has answered all clarification questions; design is concrete.

---

## 9. Implementation Order (for the writing-plans skill)

1. Add `acp_agents.pi` block to `config.example.yaml`; bump `config_version`
2. Modify `_build_acp_section` in `prompt.py`
3. Add 3 new tests + update 1 existing test in `test_lead_agent_prompt.py`
4. Create `scripts/bundle-pi-coding-agent.sh`; chmod +x
5. Create `scripts/bundle-pi-acp.sh`; chmod +x
6. Create `scripts/bundle-pi-web.sh`; chmod +x
7. Add commented-out `pi-coding-agent` + `pi-acp` install blocks to `backend/Dockerfile` (builder + runtime)
8. Update `backend/CLAUDE.md` ACP section to mention `pi`
9. Add new doc (e.g. `docs/PI_ACP.md` or extend `docs/ACP_AGENTS.md`)
10. Verify: `cd backend && make lint && make test`
11. Verify: run each bundle script on Linux x86_64 (out of scope for CI, manual)
12. Commit + PR
