import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test.use({ viewport: { width: 1280, height: 960 } });

test("project memory: inspect, toggle, promote and delete", async ({
  page,
  context,
  baseURL,
}) => {
  const project = {
    id: "project-memory-demo",
    name: "Q4 财报分析",
    instructions: "本项目用于 Q4 财报分析，所有输出使用中文。",
  };
  let enabled = true;
  let facts = [
    "报表金额口径一律不含税",
    "数据拉取统一使用 v2 接口",
    "对比基准年固定为 2024 年",
  ].map((content, i) => ({
    id: `project:${i}`,
    content,
    source_thread_id: "demo-chat",
    created_at: "2026-11-10T10:00:00Z",
  }));
  mockLangGraphAPI(page, { projects: [project] });
  await page.route(`**/api/projects/${project.id}`, async (route) => {
    if (route.request().method() === "PATCH")
      Object.assign(project, route.request().postDataJSON());
    await route.fulfill({
      json: {
        ...project,
        status: "active",
        presentation: {},
        created_at: "",
        updated_at: "",
      },
    });
  });
  await page.route(`**/api/projects/${project.id}/memory**`, async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (method === "PATCH")
      enabled = (route.request().postDataJSON() as { enabled: boolean })
        .enabled;
    if (method === "DELETE")
      facts = facts.filter(
        (fact) => fact.id !== decodeURIComponent(path.split("/").at(-1)!),
      );
    if (method === "POST") {
      const id = decodeURIComponent(path.split("/").at(-2)!);
      const fact = facts.find((item) => item.id === id)!;
      project.instructions += `\n- ${fact.content}`;
      facts = facts.filter((item) => item.id !== id);
      await route.fulfill({
        json: {
          instructions: project.instructions,
          memory: { enabled, facts, max_facts: 30 },
        },
      });
      return;
    }
    await route.fulfill({ json: { enabled, facts, max_facts: 30 } });
  });
  await context.addCookies([{ name: "locale", value: "zh-CN", url: baseURL! }]);
  await page.goto(`/workspace/projects/${project.id}`);
  await page.getByRole("tab", { name: "指令", exact: true }).click();
  await expect(page.getByRole("heading", { name: "项目记忆" })).toBeVisible();
  await expect(page.getByText("3 / 30")).toBeVisible();
  await page.screenshot({
    path:
      process.env.PROJECT_MEMORY_SCREENSHOT ??
      "test-results/project-memory.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("switch", { name: "自动提取" }).click();
  await expect(
    page.getByRole("switch", { name: "自动提取" }),
  ).not.toBeChecked();
  await expect(
    page.getByText("报表金额口径一律不含税", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "转入指令", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("textbox", { name: "指令", exact: true }),
  ).toHaveValue(/报表金额口径一律不含税/);
  await expect(page.getByText("2 / 30")).toBeVisible();
  await page
    .getByRole("button", { name: "删除: 数据拉取统一使用 v2 接口" })
    .click();
  await expect(page.getByText("1 / 30")).toBeVisible();
  await page.reload();
  await page.getByRole("tab", { name: "指令", exact: true }).click();
  await expect(
    page.getByRole("switch", { name: "自动提取" }),
  ).not.toBeChecked();
  await expect(page.getByText("1 / 30")).toBeVisible();
});
