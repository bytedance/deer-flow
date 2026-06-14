# Memory: Cognitive Style

Design note for contributors. Explains `user.cognitiveStyle` and related memory/prompt touchpoints.

## One-line pitch

**Skills teach the agent how to do tasks; memory’s `cognitiveStyle` teaches the agent how to think and collaborate with this user.**

## Problem

Cross-session memory already stores work context, personal preferences, and facts. In practice, two gaps show up:

1. **Semantic mixing** — “Prefers TypeScript” and “Always wants conclusions first, then details” both land in `personalContext` or `behavior` facts. The model must infer which is *collaboration protocol* vs *project preference*.
2. **Wrong layer for collaboration prefs** — Task skills (`SKILL.md`) are procedural and shared. Stable response/collaboration preferences (structure, depth, correction style) are **user-scoped slow variables**, not one-off task steps.

Without an explicit slot, collaboration style is under-specified in injection and easy to drop under token pressure.

## Approach (not a new subsystem)

Extend the existing memory pipeline:

| Layer | Role |
|-------|------|
| `user.cognitiveStyle.summary` | 2–4 sentence paragraph: reasoning & collaboration habits |
| `facts[]` with `category: cognitive` | Atomic, confidence-ranked supplements |
| `normalize_memory_data()` | Backward-compatible fill for older `memory.json` files |
| `MEMORY_UPDATE_PROMPT` | LLM sets `cognitiveStyle.shouldUpdate` only when new signals are clear |
| `format_memory_for_injection()` | Injects as `Thinking Style:` under User Context |

**Non-goals (this change):**

- Vector / embedding “personality library”
- Separate debounce or sampling schedule for `cognitiveStyle` only
- Replacing `personalContext` or skills

## Update frequency (read vs write)

| Event | Behavior |
|-------|----------|
| **Read (every turn)** | If `injection_enabled`, current `cognitiveStyle` is loaded into `<memory>` within `max_injection_tokens` |
| **Write (after turn)** | `MemoryMiddleware` queues filtered conversation; **debounce** (`debounce_seconds`, default 30s) batches updates |
| **Write (cognitive field)** | Same LLM pass as other user sections; field changes only when JSON has `cognitiveStyle.shouldUpdate: true` |

So: conversations **trigger** the memory job often; **cognitiveStyle text changes** only when the updater model sees durable new evidence—not every chit-chat turn.

## How this differs from nearby concepts

| Concept | Scope | Lifetime |
|---------|--------|----------|
| **Thread / checkpointer** | This session’s messages & tools | Session |
| **Skill** | How to run a task type | Shared / installable |
| **workContext / topOfMind** | What the user is doing | Cross-session, changes often |
| **personalContext** | Language, interests, tone | Cross-session |
| **cognitiveStyle** | How they reason, structure answers, give feedback | Cross-session, **slow** |
| **fact (`cognitive`)** | One line habit or meta-preference | Cross-session, ranked by confidence |

## Adding a new memory field (schema evolution)

When extending `memory.json` (new `user.*` or `history.*` section, or fact category), keep **read**, **import**, and **API** paths aligned so older exports still work.

| Step | Location |
|------|----------|
| 1. Backend normalize | `deerflow/agents/memory/storage.py` — add key to the `user` / `history` loops in `normalize_memory_data()`; update `create_empty_memory()` |
| 2. Frontend normalize | `frontend/src/core/memory/import-memory.ts` — add key to `USER_SECTION_KEYS` or `HISTORY_SECTION_KEYS` |
| 3. Types & API models | `frontend/src/core/memory/types.ts`, `backend/app/gateway/routers/memory.py` (`UserContext` / `HistoryContext`) |
| 4. Updater prompt | `deerflow/agents/memory/prompt.py` — `MEMORY_UPDATE_PROMPT` section + injection in `format_memory_for_injection()`; if adding a **fact category**, also sync `FACT_EXTRACTION_PROMPT` JSON union and `Categories:` list |
| 5. Settings UI & i18n | `memory-settings-page.tsx`, `en-US.ts` / `zh-CN.ts` |
| 6. Tests | Backend: `tests/test_memory_normalize.py` (legacy fixture missing the new field). Frontend: `tests/unit/core/memory/import-memory.test.ts` |
| 7. Import path | Settings import must use `normalizeMemoryPayload()` — **do not** require the new field in a strict-only type guard |

**Avoid:** backend `normalize_memory_data()` accepting legacy files while frontend import rejects them (strict `isImportedMemory`-style checks without normalize first).

## Verification

```bash
cd backend
PYTHONPATH=. uv run pytest tests/test_memory_normalize.py tests/test_memory_updater.py -v -k cognitive
PYTHONPATH=. uv run pytest tests/test_memory_router.py -v

cd ../frontend
pnpm test tests/unit/core/memory
```

Manual:

1. Enable `memory` in `config.yaml`, run `make dev`.
2. In a thread, state a stable collaboration rule (e.g. “先给结论，不要长铺垫”).
3. Wait ≥ `debounce_seconds`, open **Settings → Memory** or `GET /api/memory`.
4. Confirm `user.cognitiveStyle.summary` and/or a `cognitive` fact; start a **new thread** and check behavior.

## Issue

**Title:** `feat(memory): add cognitiveStyle for stable reasoning & collaboration habits`

**Summary:**

- Adds `user.cognitiveStyle` to memory schema with backward-compatible normalization.
- Teaches the memory updater to extract thinking/collaboration habits separately from work/personal context.
- Injects as `Thinking Style:` in system prompt; supports `cognitive` fact category.
- Documents rationale in `backend/docs/MEMORY_COGNITIVE_STYLE.md` and harness memory docs.

**Motivation:** Cross-session memory should distinguish project context from stable collaboration preferences (response structure, correction style, depth). This change extends the existing memory harness only; it does not add a new store.

---

## 中文说明

### 背景

跨会话 memory 已有 `workContext`、`personalContext` 与 `behavior` 类 facts。实践中两类信息容易混在同一字段里：

- 项目/工具偏好（例如常用 TypeScript）
- 协作偏好（例如先给结论、控制篇幅、纠错方式）

后者更新频率低于 `topOfMind`，又不同于一次性会话信息。单独增加 `user.cognitiveStyle` 便于注入时固定展示为 `Thinking Style:`，并与任务级 Skill 区分。

### 实现范围

- 扩展 `memory.json` schema，`normalize_memory_data()` 兼容旧文件
- `MEMORY_UPDATE_PROMPT` 输出 `cognitiveStyle.shouldUpdate`；可选 `category: cognitive` 的 facts
- 复用现有 Middleware → 防抖队列 → Updater → 注入链路，不新增子系统

### 更新频率

| 事件 | 行为 |
|------|------|
| 每轮对话开始 | 在 `max_injection_tokens` 内注入已有 `cognitiveStyle`（读） |
| 每轮对话结束 | 与其它 memory 段相同，可能入队；默认 `debounce_seconds` 合并 |
| 写入 `cognitiveStyle` | 仅当 LLM 返回 `shouldUpdate: true` 时更新段落 |

### 与 Skill 的区别

| 类型 | 内容 |
|------|------|
| Skill | 某类任务的步骤与模板（可共享、可安装） |
| `cognitiveStyle` | 该用户稳定的回复结构、讨论深度、反馈习惯（按用户持久化） |

### 以后新增 memory 字段时

按上文 **Adding a new memory field** 清单同步改后端 `normalize_memory_data()` 与前端 `normalizeMemoryPayload()`；导入走 normalize，不要只对完整新 schema 做严校验。
