import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const CHAT = "00000000-0000-0000-0000-000000000901";
const OTHER = "00000000-0000-0000-0000-000000000902";

test("archive keeps the open conversation, supports undo and restores from the archive", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: CHAT,
        title: "Finished report",
        updated_at: "2026-07-04T10:00:00Z",
        metadata: { deerflow_pinned: true },
      },
      {
        thread_id: OTHER,
        title: "Current work",
        updated_at: "2026-07-05T10:00:00Z",
      },
    ],
  });
  await page.goto(`/workspace/chats/${CHAT}`, {
    waitUntil: "domcontentloaded",
  });
  const sidebarLink = page.locator(
    `a[data-sidebar="menu-button"][href="/workspace/chats/${CHAT}"]`,
  );
  const archive = async () => {
    await sidebarLink.hover();
    await sidebarLink
      .locator("xpath=..")
      .getByRole("button", { name: "More" })
      .click();
    await page
      .getByRole("menuitem", { name: "Archive chat", exact: true })
      .click();
  };
  await expect(sidebarLink).toBeVisible();
  await archive();
  await expect(sidebarLink).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(CHAT));
  await expect(
    page.getByRole("button", { name: "Restore chat", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(sidebarLink).toBeVisible();
  await archive();
  await expect(sidebarLink).toHaveCount(0);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(
    page.getByRole("button", { name: "Restore chat", exact: true }),
  ).toBeVisible();
  await page.goto("/workspace/chats", { waitUntil: "domcontentloaded" });
  await expect(
    page.locator("main").getByText("Current work", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Archived", exact: true }).click();
  await expect(
    page.locator("main").getByText("Finished report", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("tab", { name: "Archived", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.screenshot({
    path: testInfo.outputPath("archived-list.png"),
    animations: "disabled",
  });
  await page
    .locator("main")
    .getByRole("button", { name: "Restore chat", exact: true })
    .click();
  await expect(
    page.getByText("No archived chats", { exact: true }),
  ).toBeVisible();
  await expect(sidebarLink).toBeVisible();
});

test("failed archive keeps the chat visible", async ({ page }) => {
  mockLangGraphAPI(page, { threads: [{ thread_id: CHAT, title: "Keep me" }] });
  await page.route(`**/api/threads/${CHAT}`, (route) =>
    route.request().method() === "PATCH"
      ? route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Unavailable" }),
        })
      : route.fallback(),
  );
  await page.goto("/workspace/chats/new");
  const link = page.locator(
    `a[data-sidebar="menu-button"][href="/workspace/chats/${CHAT}"]`,
  );
  await link.hover();
  await link.locator("xpath=..").getByRole("button", { name: "More" }).click();
  await page
    .getByRole("menuitem", { name: "Archive chat", exact: true })
    .click();
  await expect(
    page.getByText("Failed to update archived chat", { exact: true }),
  ).toBeVisible();
  await expect(link).toBeVisible();
});

test("active list includes legacy chats beyond a full page of archived chats", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      ...Array.from({ length: 55 }, (_, index) => ({
        thread_id: `archived-${index}`,
        title: `Archived ${index}`,
        updated_at: new Date(
          Date.UTC(2026, 7, 1) - index * 60000,
        ).toISOString(),
        metadata: { deerflow_archived: true },
      })),
      {
        thread_id: CHAT,
        title: "Legacy chat",
        updated_at: "2020-01-01T00:00:00Z",
      },
    ],
  });
  await page.goto("/workspace/chats", { waitUntil: "domcontentloaded" });
  await expect(
    page.locator("main").getByText("Legacy chat", { exact: true }),
  ).toBeVisible();
  await expect(
    page.locator("main").getByText("Archived 0", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("tab", { name: "Archived", exact: true }).click();
  await expect(
    page.locator("main").getByText("Archived 0", { exact: true }),
  ).toBeVisible();
});

for (const customAgent of [false, true]) {
  test(`archived ${customAgent ? "custom agent" : "default"} chat can be restored from its mobile header`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, {
      agents: [{ name: "researcher", description: "Research assistant" }],
      threads: [
        {
          thread_id: CHAT,
          title: "Archived report",
          metadata: {
            deerflow_archived: true,
            ...(customAgent ? { agent_name: "researcher" } : {}),
          },
        },
      ],
    });
    const url = customAgent
      ? `/workspace/agents/researcher/chats/${CHAT}`
      : `/workspace/chats/${CHAT}`;
    await page.goto(url, { waitUntil: "domcontentloaded" });
    const restore = page.getByRole("button", {
      name: "Restore chat",
      exact: true,
    });
    await expect(restore).toBeVisible({ timeout: 15000 });
    await expect
      .poll(() =>
        page
          .getByText("Archived report", { exact: true })
          .evaluate((element) => element.getBoundingClientRect().height),
      )
      .toBeLessThanOrEqual(24);
    await page.screenshot({
      path: testInfo.outputPath("archived-header-mobile.png"),
      animations: "disabled",
    });
    await restore.click();
    await expect(restore).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(CHAT));
  });
}
