# Frontend Bundle and Static Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore static rendering for public routes and keep locale dictionaries, settings pages, editors, artifact panels, and Shiki out of routes that do not use them.

**Architecture:** The root layout becomes locale-agnostic and static. Locale-aware route groups install scoped providers backed by one dynamically imported dictionary. Feature hosts load code at the user-interaction boundary. Syntax highlighting produces one HTML tree per code block.

**Tech Stack:** Next.js App Router, React 19, TypeScript, Rstest, Streamdown, Shiki, CodeMirror.

**Global Constraints:** Preserve visible behavior and deep links. Dynamic imports must have a stable loading/error state. Do not move authentication checks into public routes. All user-facing architecture changes update the appropriate `AGENTS.md`.

## Task 1: Make the root layout static and scope route styles

**Files:**
- Modify: `frontend/src/app/layout.tsx`
- Create or modify: `frontend/src/app/(auth)/layout.tsx`
- Modify: `frontend/src/app/workspace/layout.tsx`
- Modify: `frontend/src/app/[lang]/docs/layout.tsx`
- Modify: `frontend/src/app/blog/layout.tsx`
- Modify: `frontend/src/components/landing/header.tsx`
- Create: `frontend/tests/unit/app/layout-boundaries.test.ts`

- [ ] Write a source-boundary test asserting root layout does not import `cookies`, `detectLocaleServer`, KaTeX CSS, Streamdown CSS, or workspace providers. Assert workspace/docs layouts own only the styles they render.
- [ ] Run the focused test and capture RED.
- [ ] Reduce root layout to global reset/theme metadata and `<html lang={DEFAULT_LOCALE}>`. Pass an explicit default locale to the public landing header. Install locale/provider and rich-content CSS only in auth/workspace/docs/blog layouts that need them.
- [ ] Run the focused test GREEN and `pnpm build`. Verify `/` and `/en/docs` are emitted without request-time cookie dependency and their production responses no longer contain `private, no-store` solely because of the root layout.
- [ ] Revert root locale detection, prove RED, restore, rerun.
- [ ] Commit: `perf(frontend): restore static public layout boundaries`.

## Task 2: Load only the selected locale dictionary

**Files:**
- Modify: `frontend/src/core/i18n/context.tsx`
- Modify: `frontend/src/core/i18n/translations.ts`
- Modify: `frontend/src/core/i18n/server.ts`
- Modify: `frontend/src/core/i18n/hooks.ts`
- Create: `frontend/tests/unit/core/i18n/context.dom.test.tsx`
- Modify: `frontend/tests/unit/core/i18n/translations.test.ts`

- [ ] Write failing tests for `loadTranslations("en-US")` and `loadTranslations("zh-CN")`, provider fallback while a locale chunk loads, and `document.documentElement.lang` synchronization.
- [ ] Run focused i18n tests and capture RED.
- [ ] Replace static imports of both dictionaries with an exhaustive loader map returning `import("./locales/en-US")` or `import("./locales/zh-CN")`. Server routes pass an already selected dictionary; client-only routes suspend behind a neutral provider fallback.
- [ ] Keep the public `useI18n()` contract stable and reject unsupported locale strings through the existing locale parser.
- [ ] Run focused tests GREEN and use the route measurement output to assert a route references at most one locale chunk.
- [ ] Revert the loader map, prove the chunk-ownership test RED, restore, rerun.
- [ ] Commit: `perf(frontend): split locale dictionaries by route`.

## Task 3: Split interaction-only settings and workspace panels

**Files:**
- Modify: `frontend/src/components/settings/settings-dialog-host.tsx`
- Modify: `frontend/src/components/settings/settings-dialog.tsx`
- Modify: `frontend/src/components/workspace/settings/account-settings-page.tsx`
- Modify: `frontend/src/components/workspace/settings/appearance-settings-page.tsx`
- Modify: `frontend/src/components/workspace/settings/channels-settings-page.tsx`
- Modify: `frontend/src/components/workspace/settings/integrations-settings-page.tsx`
- Modify: `frontend/src/components/workspace/settings/memory-settings-page.tsx`
- Modify: `frontend/src/components/workspace/settings/notification-settings-page.tsx`
- Modify: `frontend/src/components/workspace/settings/skill-settings-page.tsx`
- Modify: `frontend/src/components/workspace/settings/tool-settings-page.tsx`
- Modify: `frontend/src/components/workspace/settings/about-settings-page.tsx`
- Modify: `frontend/src/components/workspace/sidecar/sidecar-panel.tsx`
- Modify: `frontend/src/components/workspace/artifacts/index.ts`
- Modify: `frontend/src/components/workspace/browser-view/index.ts`
- Modify: `frontend/src/components/workspace/changes/workspace-change-panel.tsx`
- Modify: `frontend/src/components/workspace/citations/citation-sources-panel.tsx`
- Create: `frontend/tests/unit/components/settings/settings-dialog-host.dom.test.tsx`
- Create: `frontend/tests/unit/components/workspace/lazy-panels.dom.test.tsx`

- [ ] Write failing DOM tests asserting no settings page module or closed artifact/browser panel is evaluated before its trigger opens; use module spies and a visible loading shell.
- [ ] Run focused tests and capture RED.
- [ ] Wrap the settings dialog and each heavy settings page with `next/dynamic`; use `ssr:false` only for browser-only modules. Apply the same boundary to artifact detail, browser live view, and other closed workspace panels.
- [ ] Preserve a single `SettingsDialogHost` and keyboard/deep-link opening behavior.
- [ ] Run tests GREEN and confirm the chats route no longer references settings/editor/browser chunks initially.
- [ ] Revert one boundary, prove its module-evaluation assertion RED, restore.
- [ ] Commit: `perf(frontend): defer closed workspace panels`.

## Task 4: Split CodeMirror languages and render one Shiki tree

**Files:**
- Modify: `frontend/src/components/workspace/code-editor.tsx`
- Create: `frontend/src/components/workspace/code-editor-languages.ts`
- Modify: `frontend/src/components/ai-elements/code-block.tsx`
- Create: `frontend/src/components/ai-elements/shiki-highlight.tsx`
- Create: `frontend/tests/unit/components/ai-elements/code-block.dom.test.tsx`
- Create: `frontend/tests/unit/components/workspace/code-editor.dom.test.tsx`

- [ ] Write failing tests asserting the editor imports only the selected language adapter, unknown languages fall back to plain text, and one code block calls `codeToHtml` once and creates one highlighted DOM subtree.
- [ ] Run focused tests and capture RED.
- [ ] Add an exhaustive language-to-import loader for CodeMirror modes/themes. Lazy-load the editor host only when an editable text artifact is opened.
- [ ] Lazy-load Shiki highlighting behind the code block boundary. Generate one highlighted HTML string and switch theme using Shiki CSS variables or a single dual-theme token tree, not two calls/two trees.
- [ ] Run focused tests GREEN. Assert the landing/chats initial asset list contains neither CodeMirror nor Shiki chunks.
- [ ] Revert the single-tree implementation, prove the call-count test RED, restore.
- [ ] Commit: `perf(frontend): split editors and deduplicate highlighting`.

## Task 5: Close the bundle/static gate

- [ ] Run `cd frontend && pnpm check && pnpm test`.
- [ ] Run `NEXT_PUBLIC_STATIC_WEBSITE_ONLY=true pnpm build` and `pnpm perf:check`.
- [ ] Inspect the five route asset lists and confirm each heavy chunk has one owning route/interaction.
- [ ] Commit any measurement fixture refresh separately as `test(frontend): lock optimized route budgets`; never raise a limit above the approved ceilings.
