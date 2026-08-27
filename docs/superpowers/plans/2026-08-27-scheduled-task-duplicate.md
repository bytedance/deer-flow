# Scheduled Task Duplicate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a frontend-only Duplicate action that turns an existing scheduled task into an editable create-form draft without mutating or immediately submitting it.

**Architecture:** A pure scheduled-task helper converts API task data into create-form state, including safe handling for expired one-time timestamps. The workspace page applies that draft to its existing controlled fields, remounts the schedule editor, then scrolls and focuses the form; the existing create mutation remains unchanged.

**Tech Stack:** TypeScript, React 19, Next.js App Router, TanStack Query, Rstest, Playwright, DeerFlow i18n dictionaries.

---

## File Structure

- Create `frontend/src/core/scheduled-tasks/duplicate.ts`: pure API-task-to-create-draft conversion.
- Create `frontend/tests/unit/core/scheduled-tasks/duplicate.test.ts`: edge-case and immutability coverage for the helper.
- Modify `frontend/src/app/workspace/scheduled-tasks/page.tsx`: Duplicate action, form refs, state application, scroll, and focus.
- Modify `frontend/src/core/i18n/locales/types.ts`: type the new action label and title suffix.
- Modify `frontend/src/core/i18n/locales/en-US.ts`: English `Duplicate` and ` (Copy)` strings.
- Modify `frontend/src/core/i18n/locales/zh-CN.ts`: Chinese `复制` and `（副本）` strings.
- Modify `frontend/tests/e2e/scheduled-tasks.spec.ts`: prove the action fills the form without POSTing.
- Modify `README.md` and `README_zh.md`: document reuse of an existing task as a create-form draft.

### Task 1: Pure Duplicate-Draft Conversion

**Files:**
- Create: `frontend/tests/unit/core/scheduled-tasks/duplicate.test.ts`
- Create: `frontend/src/core/scheduled-tasks/duplicate.ts`

- [ ] **Step 1: Write the failing unit tests**

Create a typed task fixture and tests covering cron copying, future and expired one-time timestamps, reuse-thread mapping, and source immutability:

```ts
import { describe, expect, it } from "@rstest/core";

import { buildScheduledTaskDuplicateDraft } from "@/core/scheduled-tasks/duplicate";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

const BASE_TASK: ScheduledTask = {
  id: "task-1",
  thread_id: null,
  context_mode: "fresh_thread_per_run",
  title: "Daily summary",
  prompt: "Summarize the workspace",
  schedule_type: "cron",
  schedule_spec: { cron: "0 9 * * *" },
  timezone: "Asia/Shanghai",
  status: "enabled",
  next_run_at: null,
  last_run_at: null,
  last_run_id: null,
  last_thread_id: null,
  last_error: null,
  run_count: 0,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("buildScheduledTaskDuplicateDraft", () => {
  it("copies a cron task into an independent create draft", () => {
    const draft = buildScheduledTaskDuplicateDraft(
      BASE_TASK,
      " (Copy)",
      new Date("2026-08-27T00:00:00Z"),
    );
    expect(draft).toEqual({
      title: "Daily summary (Copy)",
      prompt: "Summarize the workspace",
      contextMode: "fresh_thread_per_run",
      targetThreadId: "",
      schedule: {
        schedule_type: "cron",
        schedule_spec: { cron: "0 9 * * *" },
        timezone: "Asia/Shanghai",
      },
    });
    draft.schedule.schedule_spec.cron = "0 10 * * *";
    expect(BASE_TASK.schedule_spec).toEqual({ cron: "0 9 * * *" });
  });

  it("keeps a future one-time timestamp and reuse-thread identity", () => {
    const task: ScheduledTask = {
      ...BASE_TASK,
      thread_id: "thread-1",
      context_mode: "reuse_thread",
      schedule_type: "once",
      schedule_spec: { run_at: "2026-08-28T09:00:00Z" },
    };
    const draft = buildScheduledTaskDuplicateDraft(
      task,
      "（副本）",
      new Date("2026-08-27T00:00:00Z"),
    );
    expect(draft.title).toBe("Daily summary（副本）");
    expect(draft.targetThreadId).toBe("thread-1");
    expect(draft.schedule.schedule_spec).toEqual({
      run_at: "2026-08-28T09:00:00Z",
    });
  });

  it.each(["2026-08-26T09:00:00Z", "invalid", undefined])(
    "clears an unusable one-time timestamp: %s",
    (runAt) => {
      const task: ScheduledTask = {
        ...BASE_TASK,
        schedule_type: "once",
        schedule_spec: runAt ? { run_at: runAt } : {},
      };
      const draft = buildScheduledTaskDuplicateDraft(
        task,
        " (Copy)",
        new Date("2026-08-27T00:00:00Z"),
      );
      expect(draft.schedule.schedule_spec).toEqual({});
    },
  );
});
```

- [ ] **Step 2: Run the unit test to verify it fails**

Run:

```bash
cd frontend && python3 ../scripts/pnpm.py rstest run tests/unit/core/scheduled-tasks/duplicate.test.ts
```

Expected: FAIL because `@/core/scheduled-tasks/duplicate` does not exist.

- [ ] **Step 3: Implement the minimal pure helper**

Create `duplicate.ts` with a UI-independent draft shape:

```ts
import type { ScheduledTask } from "./types";

export type ScheduledTaskDuplicateDraft = {
  title: string;
  prompt: string;
  contextMode: ScheduledTask["context_mode"];
  targetThreadId: string;
  schedule: {
    schedule_type: ScheduledTask["schedule_type"];
    schedule_spec: { cron?: string; run_at?: string };
    timezone: string;
  };
};

export function buildScheduledTaskDuplicateDraft(
  task: ScheduledTask,
  titleSuffix: string,
  now = new Date(),
): ScheduledTaskDuplicateDraft {
  const cron = task.schedule_spec.cron;
  const runAt = task.schedule_spec.run_at;
  const parsedRunAt = typeof runAt === "string" ? Date.parse(runAt) : NaN;
  const scheduleSpec =
    task.schedule_type === "cron"
      ? typeof cron === "string"
        ? { cron }
        : {}
      : Number.isFinite(parsedRunAt) && parsedRunAt > now.getTime()
        ? { run_at: runAt as string }
        : {};

  return {
    title: `${task.title}${titleSuffix}`,
    prompt: task.prompt,
    contextMode: task.context_mode,
    targetThreadId:
      task.context_mode === "reuse_thread" ? (task.thread_id ?? "") : "",
    schedule: {
      schedule_type: task.schedule_type,
      schedule_spec: scheduleSpec,
      timezone: task.timezone || "UTC",
    },
  };
}
```

- [ ] **Step 4: Run the focused unit tests**

Run:

```bash
cd frontend && python3 ../scripts/pnpm.py rstest run tests/unit/core/scheduled-tasks/duplicate.test.ts
```

Expected: all duplicate-draft tests PASS.

- [ ] **Step 5: Commit the helper and tests**

```bash
git add frontend/src/core/scheduled-tasks/duplicate.ts frontend/tests/unit/core/scheduled-tasks/duplicate.test.ts
git commit -m "feat(frontend): build scheduled task duplicate drafts"
```

### Task 2: Duplicate Action and Form Population

**Files:**
- Modify: `frontend/src/app/workspace/scheduled-tasks/page.tsx`
- Modify: `frontend/src/core/i18n/locales/types.ts`
- Modify: `frontend/src/core/i18n/locales/en-US.ts`
- Modify: `frontend/src/core/i18n/locales/zh-CN.ts`
- Modify: `frontend/tests/e2e/scheduled-tasks.spec.ts`

- [ ] **Step 1: Add the failing Playwright scenario**

Add a cron task with `context_mode: "reuse_thread"`, intercept POST requests to `/api/scheduled-tasks`, click Duplicate, and assert:

```ts
test("duplicate fills the create form without creating a task", async ({
  page,
}) => {
  let createRequests = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname.endsWith("/api/scheduled-tasks")
    ) {
      createRequests += 1;
    }
  });
  mockLangGraphAPI(page, {
    threads: [],
    scheduledTasks: [
      {
        id: "task-copy-source",
        thread_id: "thread-copy-source",
        context_mode: "reuse_thread",
        title: "Daily summary",
        prompt: "Summarize this conversation",
        schedule_type: "cron",
        schedule_spec: { cron: "0 18 * * *" },
        timezone: "UTC",
        status: "enabled",
        next_run_at: "2026-08-28T18:00:00Z",
        last_run_at: null,
        last_run_id: null,
        last_thread_id: null,
        last_error: null,
        run_count: 0,
        created_at: "2026-08-01T00:00:00Z",
        updated_at: "2026-08-01T00:00:00Z",
      },
    ],
  });

  await page.goto("/workspace/scheduled-tasks");
  await page
    .getByTestId("scheduled-task-detail")
    .getByRole("button", { name: "Duplicate" })
    .click();

  const createForm = page.getByTestId("scheduled-task-create-form");
  await expect(createForm.getByPlaceholder("Task title")).toHaveValue(
    "Daily summary (Copy)",
  );
  await expect(createForm.getByPlaceholder("Prompt")).toHaveValue(
    "Summarize this conversation",
  );
  await expect(createForm.getByPlaceholder("Thread ID")).toHaveValue(
    "thread-copy-source",
  );
  await expect(createForm.getByPlaceholder("Task title")).toBeFocused();
  expect(createRequests).toBe(0);
});
```

- [ ] **Step 2: Run the scenario to verify it fails**

Run:

```bash
cd frontend && python3 ../scripts/pnpm.py playwright test tests/e2e/scheduled-tasks.spec.ts --grep "duplicate fills"
```

Expected: FAIL because the Duplicate button does not exist.

- [ ] **Step 3: Add typed localized strings**

Extend `scheduledTasks.actions` in `types.ts` with:

```ts
duplicate: string;
duplicateTitleSuffix: string;
```

Add to `en-US.ts`:

```ts
duplicate: "Duplicate",
duplicateTitleSuffix: " (Copy)",
```

Add to `zh-CN.ts`:

```ts
duplicate: "复制",
duplicateTitleSuffix: "（副本）",
```

- [ ] **Step 4: Wire the action into the page**

Update React imports to include `useRef`, import `CopyIcon`, and import the pure helper. Add refs to the create-form container and title input:

```ts
const createFormRef = useRef<HTMLDivElement>(null);
const createTitleRef = useRef<HTMLInputElement>(null);
```

Add a local handler:

```ts
const duplicateTask = (task: ScheduledTask) => {
  const draft = buildScheduledTaskDuplicateDraft(
    task,
    st.actions.duplicateTitleSuffix,
  );
  setTitle(draft.title);
  setPrompt(draft.prompt);
  setContextMode(draft.contextMode);
  setTargetThreadId(draft.targetThreadId);
  setCreateSchedule(draft.schedule);
  setFormError(null);
  setCreateNonce((nonce) => nonce + 1);
  createFormRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  createTitleRef.current?.focus();
};
```

Attach `ref={createFormRef}` to `scheduled-task-create-form` and `ref={createTitleRef}` to its title `Input`. Add the action beside Edit/Pause/Trigger/Delete:

```tsx
<Button
  variant="outline"
  size="sm"
  onClick={() => duplicateTask(selectedTask)}
>
  <CopyIcon />
  {st.actions.duplicate}
</Button>
```

- [ ] **Step 5: Run the duplicate Playwright scenario**

Run:

```bash
cd frontend && python3 ../scripts/pnpm.py playwright test tests/e2e/scheduled-tasks.spec.ts --grep "duplicate fills"
```

Expected: PASS; no create POST is observed.

- [ ] **Step 6: Commit the page behavior**

```bash
git add frontend/src/app/workspace/scheduled-tasks/page.tsx frontend/src/core/i18n/locales/types.ts frontend/src/core/i18n/locales/en-US.ts frontend/src/core/i18n/locales/zh-CN.ts frontend/tests/e2e/scheduled-tasks.spec.ts
git commit -m "feat(frontend): duplicate scheduled tasks into create form"
```

### Task 3: Documentation and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `README_zh.md`

- [ ] **Step 1: Document the user-facing action**

Add one bullet to each Scheduled Tasks feature list.

English:

```md
- Duplicate an existing task into the create form as an editable draft without copying its run history
```

Chinese:

```md
- 将现有任务复制到创建表单中作为可编辑草稿，不复制运行历史
```

- [ ] **Step 2: Run focused tests**

```bash
cd frontend && python3 ../scripts/pnpm.py rstest run tests/unit/core/scheduled-tasks
```

Expected: all scheduled-task unit tests PASS.

- [ ] **Step 3: Run the full scheduled-task E2E spec**

```bash
cd frontend && python3 ../scripts/pnpm.py playwright test tests/e2e/scheduled-tasks.spec.ts
```

Expected: all scheduled-task E2E scenarios PASS.

- [ ] **Step 4: Run frontend quality checks**

```bash
cd frontend && python3 ../scripts/pnpm.py check
cd frontend && python3 ../scripts/pnpm.py format
```

Expected: ESLint, TypeScript, and Prettier checks PASS.

- [ ] **Step 5: Inspect the final diff**

```bash
git diff --check
git status --short
git diff origin/main...HEAD --stat
```

Expected: no whitespace errors; only the design/plan docs and scheduled-task feature files are changed.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md README_zh.md
git commit -m "docs: document scheduled task duplication"
```
