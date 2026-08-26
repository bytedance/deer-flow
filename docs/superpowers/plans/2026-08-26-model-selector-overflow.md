# Model Selector Overflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep long selected-model names inside the main and sidecar composer buttons with an ellipsis.

**Architecture:** Preserve the existing shared `ModelSelectorName` truncation behavior and fix the two non-generated call sites that defeat it. Remove `items-start` from their column wrappers so the name span receives a constrained width through normal flex stretching.

**Tech Stack:** React 19, TypeScript, Tailwind CSS 4, Rstest

## Global Constraints

- Do not edit generated files under `frontend/src/components/ai-elements/`.
- Cover both the main chat composer and sidecar composer.
- Add no dependency or abstraction.

---

### Task 1: Constrain selected-model labels

**Files:**

- Create: `frontend/tests/unit/components/workspace/model-selector-overflow.test.ts`
- Modify: `frontend/src/components/workspace/input-box.tsx`
- Modify: `frontend/src/components/workspace/sidecar/sidecar-panel.tsx`

**Interfaces:**

- Consumes: `ModelSelectorName`, whose default classes already include `truncate`.
- Produces: selected-model wrappers that allow the name span to stretch to the available width.

- [ ] **Step 1: Write the failing source-level regression test**

```ts
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");
const SELECTED_MODEL_TRIGGER_PATTERN =
  /<ModelSelectorTrigger asChild>[\s\S]*?<\/ModelSelectorTrigger>/;

function source(relativePath: string) {
  return readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");
}

function selectedModelTrigger(relativePath: string) {
  return SELECTED_MODEL_TRIGGER_PATTERN.exec(source(relativePath))?.[0];
}

describe("selected model name truncation", () => {
  it.each([
    "src/components/workspace/input-box.tsx",
    "src/components/workspace/sidecar/sidecar-panel.tsx",
  ])("lets ModelSelectorName stretch in %s", (relativePath) => {
    const trigger = selectedModelTrigger(relativePath);

    expect(trigger).toContain("<ModelSelectorName");
    expect(trigger).not.toContain("items-start");
  });
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd frontend && python3 ../scripts/pnpm.py rstest run tests/unit/components/workspace/model-selector-overflow.test.ts
```

Expected: both cases fail because the wrappers still include `items-start`.

- [ ] **Step 3: Remove `items-start` from both selected-model wrappers**

Use this wrapper in both production files:

```tsx
<div className="flex min-w-0 flex-col text-left">
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
cd frontend && python3 ../scripts/pnpm.py rstest run tests/unit/components/workspace/model-selector-overflow.test.ts
```

Expected: 2 tests pass.

- [ ] **Step 5: Run frontend verification**

Run:

```bash
cd frontend && python3 ../scripts/pnpm.py test
cd frontend && python3 ../scripts/pnpm.py check
```

Expected: all unit tests, lint, formatting, and type checks pass.

- [ ] **Step 6: Commit the fix**

```bash
git add docs/superpowers/specs/2026-08-26-model-selector-overflow-design.md \
  docs/superpowers/plans/2026-08-26-model-selector-overflow.md \
  frontend/tests/unit/components/workspace/model-selector-overflow.test.ts \
  frontend/src/components/workspace/input-box.tsx \
  frontend/src/components/workspace/sidecar/sidecar-panel.tsx
git commit -m "fix(frontend): truncate selected model names"
```
