import { test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const AGENTS = [
  {
    name: "research-analyst",
    description: "Investigates technical topics and produces concise reports.",
    model: "gpt-5",
    tool_groups: ["web", "files"],
    skills: ["research", "reports"],
    soul: "Be precise, cite sources, and keep conclusions actionable.",
  },
  {
    name: "code-reviewer",
    description: "Reviews code changes for correctness and regression risk.",
    model: "gpt-5",
    tool_groups: ["files"],
    skills: ["code-review"],
  },
];

const TASKS = [
  {
    id: "task-visual-1",
    thread_id: null,
    context_mode: "fresh_thread_per_run" as const,
    last_thread_id: "thread-last",
    title: "Daily engineering brief",
    prompt: "Summarize the most important changes and blockers.",
    schedule_type: "cron" as const,
    schedule_spec: { cron: "0 9 * * *" },
    timezone: "Asia/Shanghai",
    status: "enabled" as const,
    next_run_at: "2026-07-23T01:00:00+00:00",
    last_run_at: "2026-07-22T01:00:00+00:00",
    last_run_id: "run-visual-1",
    last_error: null,
    run_count: 12,
    created_at: "2026-07-01T00:00:00+00:00",
    updated_at: "2026-07-22T01:00:00+00:00",
  },
  {
    id: "task-visual-2",
    thread_id: null,
    context_mode: "fresh_thread_per_run" as const,
    last_thread_id: null,
    title: "Weekly issue triage",
    prompt: "Triage open issues and identify good first issues.",
    schedule_type: "cron" as const,
    schedule_spec: { cron: "0 9 * * 1" },
    timezone: "Asia/Shanghai",
    status: "paused" as const,
    next_run_at: null,
    last_run_at: null,
    last_run_id: null,
    last_error: null,
    run_count: 0,
    created_at: "2026-07-01T00:00:00+00:00",
    updated_at: "2026-07-22T01:00:00+00:00",
  },
];

for (const viewport of [
  { name: "desktop", width: 1440, height: 960 },
  { name: "mobile", width: 390, height: 844 },
]) {
  test(`visual baseline ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    mockLangGraphAPI(page, {
      agents: AGENTS,
      scheduledTasks: TASKS,
      threads: [],
    });

    for (const [name, path] of [
      ["welcome", "/workspace/chats/new"],
      ["agents", "/workspace/agents"],
      ["scheduled-tasks", "/workspace/scheduled-tasks"],
    ] as const) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await page.screenshot({
        path: testInfo.outputPath(`${name}-${viewport.name}.png`),
        fullPage: true,
      });
    }
  });
}
