# Workspace Entry Navigation Performance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent `/workspace` entry from loading CodeMirror-heavy artifact detail code before the user opens an artifact.

**Architecture:** The confirmed bottleneck is the chat shell's eager import chain: `ChatPage` renders `ChatBox`, `ChatBox` statically imports `ArtifactFileDetail`, and `ArtifactFileDetail` statically imports `CodeEditor` plus markdown preview tooling. The fix is to keep the artifact panel shell in the initial route, but move `ArtifactFileDetail` behind a lazy boundary so the editor stack is only requested after an artifact is actually selected.

**Tech Stack:** Next.js 16 App Router, React 19 client components, Docker dev environment, bash regression script.

---

### Task 1: Freeze The Current Regression Signal

**Files:**
- Test: `scripts/debug/check-workspace-entry-codemirror.sh`

**Step 1: Run the existing failing regression script**

Run:

```bash
scripts/debug/check-workspace-entry-codemirror.sh
```

Expected:

```text
FAIL: workspace initial HTML eagerly includes CodeMirror-related assets.
```

**Step 2: Keep the script output as the before-fix baseline**

Expected evidence:
- The script reports one or more `codemirror` matches.
- Sample asset paths include `/_next/static/chunks/...codemirror...`.

**Step 3: Commit nothing yet**

Reason:
- This task is only the red-state baseline.

### Task 2: Break The Eager Artifact Detail Import Chain

**Files:**
- Create: `frontend/src/components/workspace/artifacts/lazy-artifact-file-detail.tsx`
- Modify: `frontend/src/components/workspace/chats/chat-box.tsx`

**Step 1: Add a dedicated lazy wrapper for artifact detail**

Create:

```tsx
"use client";

import dynamic from "next/dynamic";

const LazyArtifactFileDetail = dynamic(
  () =>
    import("./artifact-file-detail").then((mod) => ({
      default: mod.ArtifactFileDetail,
    })),
  {
    ssr: false,
  },
);

export { LazyArtifactFileDetail };
```

**Step 2: Stop `ChatBox` from importing artifact detail through the eager bundle**

Update imports in `frontend/src/components/workspace/chats/chat-box.tsx` so they look like:

```tsx
import { ArtifactFileList } from "../artifacts/artifact-file-list";
import { LazyArtifactFileDetail } from "../artifacts/lazy-artifact-file-detail";
import { useArtifacts } from "../artifacts/context";
```

Replace the detail render site with:

```tsx
{selectedArtifact ? (
  <LazyArtifactFileDetail
    className="size-full"
    filepath={selectedArtifact}
    threadId={threadId}
  />
) : (
  // existing placeholder / file list branch
)}
```

**Step 3: Keep the artifact panel shell behavior unchanged**

Do not change:
- `artifactPanelOpen` layout logic
- placeholder empty state
- artifact list rendering when files exist

Only the detail component should move behind the lazy boundary.

**Step 4: Run the regression script again**

Run:

```bash
scripts/debug/check-workspace-entry-codemirror.sh
```

Expected:

```text
PASS: workspace initial HTML does not include CodeMirror-related assets.
```

### Task 3: Verify Artifact Detail Still Works When Actually Needed

**Files:**
- Modify: `frontend/src/components/workspace/chats/chat-box.tsx`
- Modify: `frontend/src/components/workspace/artifacts/lazy-artifact-file-detail.tsx`

**Step 1: Add a lightweight loading fallback only if the panel flashes empty**

If needed, expand the lazy wrapper to use a minimal loading placeholder:

```tsx
loading: () => <div className="size-full" />
```

Only add this if manual smoke testing shows an obvious blank flash.

**Step 2: Smoke test the artifact path in Docker**

Manual check:
1. Open an existing thread that has artifacts.
2. Open the artifact panel.
3. Select a code artifact.

Expected:
- The panel still opens.
- The file detail renders.
- Code content still appears inside the editor view.

**Step 3: Do not broaden the fix**

Do not mix in:
- `/workspace` redirect changes
- settings dialog lazy-loading
- unrelated sidebar or query refactors

If the page is still slow after this fix, investigate the next root cause in a separate pass.

### Task 4: Final Verification And Commit

**Files:**
- Test: `scripts/debug/check-workspace-entry-codemirror.sh`
- Modify: `frontend/src/components/workspace/chats/chat-box.tsx`
- Create/Modify: `frontend/src/components/workspace/artifacts/lazy-artifact-file-detail.tsx`

**Step 1: Run frontend static checks in the frontend container**

Run:

```bash
docker exec deer-flow-frontend sh -lc "cd /app/frontend && pnpm lint"
docker exec deer-flow-frontend sh -lc "cd /app/frontend && pnpm typecheck"
```

Expected:
- Both commands exit successfully.

**Step 2: Re-run the regression script one final time**

Run:

```bash
scripts/debug/check-workspace-entry-codemirror.sh
```

Expected:
- `PASS` and zero `codemirror` matches in initial HTML.

**Step 3: Commit the focused change**

```bash
git add \
  scripts/debug/check-workspace-entry-codemirror.sh \
  frontend/src/components/workspace/chats/chat-box.tsx \
  frontend/src/components/workspace/artifacts/lazy-artifact-file-detail.tsx \
  docs/plans/2026-03-30-workspace-entry-navigation-performance.md
git commit -m "fix: lazy load artifact detail on workspace entry"
```
