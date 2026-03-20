# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Thinktank.ai Frontend is a Vite + React + Electron desktop application for an AI agent system. It communicates with a LangGraph-based backend to provide thread-based AI conversations with streaming responses, artifacts, and a skills/tools system. The app runs on macOS, Windows, and Linux.

**Stack**: Vite, React 19, React Router 7, TypeScript 5.8, Tailwind CSS 4, Electron, pnpm 10.26.2

## Commands

| Command | Purpose |
|---------|---------|
| `pnpm dev` | Dev server (http://localhost:3000) |
| `pnpm dev:electron` | Dev server with Electron |
| `pnpm dev:web` | Web-only dev (no Electron) |
| `pnpm build` | Production build (renderer) |
| `pnpm build:electron` | Full Electron build |
| `pnpm build:mac` | Package for macOS |
| `pnpm build:win` | Package for Windows |
| `pnpm build:linux` | Package for Linux |
| `pnpm check` | Lint + type check (run before committing) |
| `pnpm lint` | ESLint only |
| `pnpm lint:fix` | ESLint with auto-fix |
| `pnpm typecheck` | TypeScript type check (`tsc --noEmit`) |

No test framework is configured.

## Architecture

```
Electron App
  ├── Main Process (electron/main.ts)
  │     ├── IPC Handlers (config, dialogs, window controls)
  │     ├── Native Menus
  │     └── Auto-Updater
  │
  └── Renderer Process (Vite + React)
        ├── React Router (client-side routing)
        ├── Components (Shadcn UI, workspace, landing)
        ├── Core Logic (threads, API, i18n, settings)
        └── LangGraph SDK ──▶ LangGraph Backend
```

The frontend is a stateful chat application. Users create **threads** (conversations), send messages, and receive streamed AI responses. The backend orchestrates agents that can produce **artifacts** (files/code) and **todos**.

### Source Layout

- **`electron/`** — Electron main process:
  - `main.ts` — Main process entry, window creation
  - `preload.ts` — Secure IPC bridge via contextBridge
  - `menu.ts` — Native application menus
  - `updater.ts` — Auto-update logic
  - `ipc/` — IPC handlers (config, dialogs, window, update)
- **`src/`** — Renderer process (React app):
  - `main.tsx` — Vite entry point
  - `App.tsx` — Root component with providers
  - `router.tsx` — React Router configuration
  - `env.ts` — Environment variables
  - `pages/` — Route components (Landing, Workspace, Chat, ChatList)
  - `components/` — React components:
    - `ui/` — Shadcn UI primitives (auto-generated)
    - `ai-elements/` — Vercel AI SDK elements (auto-generated)
    - `workspace/` — Chat page components
    - `landing/` — Landing page sections
  - `core/` — Business logic:
    - `threads/` — Thread creation, streaming, state management
    - `api/` — LangGraph client singleton
    - `agent/` — Agent context API client (tools/skills panel)
    - `artifacts/` — Artifact loading and caching
    - `i18n/` — Internationalization (en-US, zh-CN)
    - `settings/` — User preferences in localStorage
    - `memory/` — Persistent user memory system
    - `skills/` — Skills installation and management
  - `hooks/` — Shared React hooks
  - `lib/` — Utilities (`cn()` from clsx + tailwind-merge)
  - `styles/` — Global CSS with Tailwind v4

### Data Flow

1. User input → thread hooks (`core/threads/hooks.ts`) → LangGraph SDK streaming
2. Stream events update thread state (messages, artifacts, todos)
3. TanStack Query manages server state; localStorage stores user settings
4. Components subscribe to thread state and render updates

Reasoning (model thoughts) rendering reads from `core/messages/utils.ts`, which supports `reasoning_content`, `reasoning` metadata, and Responses API `reasoning` content blocks.

### Key Patterns

- **Client-side routing** with React Router v7
- **Thread hooks** (`useThreadStream`, `useSubmitThread`, `useThreads`) are the primary API interface
- **LangGraph client** is a singleton obtained via `getAPIClient()` in `core/api/`
- **Electron IPC** for native features (file dialogs, window controls, auto-update)
- **HashRouter** in Electron (for file:// protocol compatibility), BrowserRouter in web mode
- **Local settings** are loaded synchronously on mount to avoid transient defaults overriding the user's model selection
- **Provider settings** are configured in Settings → Models, including `epfl-rcp` for EPFL RCP AIaaS (OpenAI-compatible `https://inference-rcp.epfl.ch/v1`); these models default to thinking-capable mode selection
- **Thinking blocks** auto-expand while streaming, auto-scroll to new tokens, and scroll within a capped height
- **Tool call timeline** renders tool outputs (including the `reflection` scratchpad) in the chain-of-thought list

## Code Style

- **Imports**: Enforced ordering (builtin → external → internal → parent → sibling), alphabetized, newlines between groups. Use inline type imports: `import { type Foo }`.
- **Unused variables**: Prefix with `_`.
- **Class names**: Use `cn()` from `@/lib/utils` for conditional Tailwind classes.
- **Path alias**: `@/*` maps to `src/*`.
- **Components**: `ui/` and `ai-elements/` are generated from registries (Shadcn, MagicUI, React Bits, Vercel AI SDK) — don't manually edit these.

## Environment

Backend API URLs are optional; the Vite dev server proxies to localhost:
```
VITE_BACKEND_BASE_URL=http://localhost:8001
VITE_LANGGRAPH_BASE_URL=http://localhost:2024
VITE_STATIC_WEBSITE_ONLY=false
```

Requires Node.js 22+ and pnpm 10.26.2+.

## Testing Conventions

### TDD Workflow
- Always write failing tests BEFORE implementation
- Use AAA pattern: Arrange-Act-Assert
- One assertion per test when possible
- Test names describe behavior: "should_return_empty_when_no_items"

### Test-First Rules
- When I ask for a feature, write tests first
- Tests should FAIL initially (no implementation exists)
- Only after tests are written, implement minimal code to pass
