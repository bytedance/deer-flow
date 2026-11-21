---
name: use-lithtrix
description: Use this skill at the start and end of every research session to give this DeerFlow instance persistent memory that survives restarts and carries across frameworks. Load Lithtrix memory/commons context before starting research to skip redundant searches on already-explored topics; save vetted findings back to Lithtrix at the end of the session. Trigger whenever LITHTRIX_API_KEY is configured.
---

# ltx-ceiling: demo uses commons as a portability substrate — not a memory replacement

## When to use

At the **start** and **end** of every DeerFlow research session when Lithtrix compounding is enabled.

**Positioning (R4):** DeerFlow already has session memory. Lithtrix gives that memory somewhere **portable** to go — across runs, instances, and frameworks. Do not frame as "DeerFlow needs memory."

## Session start (Run B and later)

1. **`lithtrix_memory_context`** — reload this agent's top memories (importance + recency). **Free** (MIRC base).
2. **`lithtrix_commons_read`** — list opt-in shared entries (`page=1`, `per_page=20`). **Free** (no credit debit; rate limits apply).

Use retrieved keys and commons summaries to **skip redundant searches** when a vetted source or finding already exists.

## Session end (every run, including Run A)

1. **`lithtrix_memory_set`** — persist vetted findings under agent-scoped keys (e.g. `deerflow:{topic_slug}:findings`). **Free**.
2. **`lithtrix_feedback`** — one helpful signal per validated source used (batch at end; do not fire per-source during the loop unless async). **Free**.
3. **Commons publish (optional, operator-scoped):** `lithtrix_memory_set` with `is_commons: true` on a **single high-confidence** key only when findings are operator-vetted. Requires root or `commons-publish` scoped key. **R1:** do not open unfiltered global commons write — this demo writes only under the registered demo agent's publisher identity.

## Scoping (R1 — commons poisoning)

| Surface | R1 scope |
|---------|----------|
| Memory keys | `{agent_id}`-isolated via Bearer |
| Commons write | Publisher = this agent only; `is_commons: true` on explicit keys |
| Commons read | Global opt-in catalog (read does not accept arbitrary writes) |

No cross-operator commons poisoning in Rung 1 — each write is attributed to the demo agent DID.

## Cost split (R5 — MIRC)

| Lithtrix call | Metered? |
|---------------|----------|
| `lithtrix_memory_context` | No |
| `lithtrix_commons_read` | No |
| `lithtrix_memory_set` | No |
| `lithtrix_feedback` | No |
| `lithtrix_search` / `lithtrix_browse` (if DeerFlow calls them) | Yes — cost-bearing tools |

DeerFlow's own web research tools are separate from Lithtrix MIRC base.

## MCP config (DeerFlow `extensions_config.json`)

See `docs/examples/lithtrix/extensions_config.snippet.json` for the `mcpServers` block. `LITHTRIX_API_KEY` and `LITHTRIX_API_URL` are referenced via `$VAR` substitution and must be set in DeerFlow's `.env` (gitignored) — never commit the raw key.

**Verified working end-to-end 2026-07-11** on a real local DeerFlow Gateway install: `.env` + `extensions_config.json` + `skills/public/use-lithtrix/SKILL.md` in place, confirmed live and enabled in DeerFlow's own Settings → Tools and Settings → Skills panels after `make dev`. No manual re-registration needed on subsequent starts — DeerFlow reads the config fresh each boot.

Required tools visible in `list_tools`: `lithtrix_memory_set`, `lithtrix_memory_context`, `lithtrix_commons_read`, `lithtrix_feedback`.

## Multi-user isolation (R2)

Do **not** claim Lithtrix solves DeerFlow multi-user isolation — DeerFlow PR #1127 addresses that natively. This skill is for **cross-run / cross-framework portability** (H4).
