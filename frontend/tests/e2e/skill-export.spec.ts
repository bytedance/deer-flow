import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const preview = {
  skill_name: "demo",
  revision: "a".repeat(64),
  can_export: true,
  file_count: 1,
  directory_count: 1,
  total_bytes: 20,
  files: [{ path: "SKILL.md", type: "file", size: 20, executable: false }],
  requirements: {
    compatibility: "Python 3.12",
    allowed_tools: ["bash"],
    required_secrets: [{ name: "DEMO_TOKEN", optional: false }],
  },
  warnings: [],
  blockers: [],
};

test("custom export previews, handles stale content and downloads only after refresh", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    skills: [
      {
        name: "demo",
        description: "Synthetic UI fixture",
        category: "custom",
        enabled: false,
      },
      {
        name: "public-demo",
        description: "Public fixture",
        category: "public",
      },
    ],
  });
  let previews = 0,
    downloads = 0;
  await page.route("**/api/skills/custom/demo/export-manifest", (route) => {
    previews++;
    return route.fulfill({ json: preview });
  });
  await page.route("**/api/skills/custom/demo/export?*", (route) => {
    downloads++;
    expect(
      new URL(route.request().url()).searchParams.get("expected_revision"),
    ).toBe(preview.revision);
    return downloads === 1
      ? route.fulfill({
          status: 409,
          json: { detail: { code: "skill_changed", message: "Changed" } },
        })
      : route.fulfill({
          contentType: "application/zip",
          body: Buffer.from("synthetic transport fixture"),
        });
  });
  await page.goto("/workspace/chats/new?settings=skills");
  await expect(
    page.getByRole("button", { name: "Export public-demo" }),
  ).toHaveCount(0);
  await page.getByRole("tab", { name: "Custom", exact: true }).click();
  await page.getByRole("button", { name: "Export demo", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "Export skill",
    exact: true,
  });
  await expect(dialog.getByText("DEMO_TOKEN (required)")).toBeVisible();
  await dialog.getByRole("button", { name: "Download .skill" }).click();
  await expect(
    dialog.getByText(
      "The skill changed. Refresh the file list before downloading.",
    ),
  ).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Download .skill" }),
  ).toBeDisabled();
  const beforeRefresh = previews;
  await dialog.getByRole("button", { name: "Refresh file list" }).click();
  await expect(
    dialog.getByRole("button", { name: "Download .skill" }),
  ).toBeEnabled();
  const download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download .skill" }).click();
  expect((await download).suggestedFilename()).toBe("demo.skill");
  await expect(
    dialog.getByText("File handed to your browser for download."),
  ).toBeVisible();
  expect(previews).toBe(beforeRefresh + 1);
  expect(downloads).toBe(2);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(
    page.getByRole("dialog", { name: "Settings", exact: true }),
  ).toBeVisible();
});

test("mobile manifest blockers are readable and cannot download", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  mockLangGraphAPI(page, {
    skills: [
      { name: "demo", description: "Synthetic UI fixture", category: "custom" },
    ],
  });
  await page.route("**/api/skills/custom/demo/export-manifest", (route) =>
    route.fulfill({
      json: {
        ...preview,
        revision: null,
        can_export: false,
        blockers: [
          {
            code: "skill_export_link",
            message: "Linked files or directories cannot be exported.",
            path: "scripts/linked",
          },
        ],
      },
    }),
  );
  await page.goto("/workspace/chats/new?settings=skills");
  await page.getByRole("tab", { name: "Custom", exact: true }).click();
  await page.getByRole("button", { name: "Export demo", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "Export skill",
    exact: true,
  });
  await expect(
    dialog.getByText("This package cannot be exported"),
  ).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Download .skill" }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
