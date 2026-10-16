import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("YAML diagnostics stay separate and reload restores a corrected skill", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page, { skills: [] });
  let corrected = false;
  let reloads = 0;
  await page.route("**/api/skills/diagnostics/custom", (route) =>
    route.fulfill({
      json: {
        diagnostics: corrected
          ? []
          : [
              {
                package: "collect-startrun",
                path: "SKILL.md",
                code: "invalid_frontmatter",
                hint: "quote_colon_value",
                line: 3,
                column: 27,
              },
            ],
      },
    }),
  );
  await page.route("**/api/skills", (route) =>
    route.fulfill({
      json: {
        skills: corrected
          ? [
              {
                name: "collect-startrun",
                description: "Collect project updates",
                category: "custom",
                enabled: true,
                editable: true,
              },
            ]
          : [],
      },
    }),
  );
  await page.route("**/api/skills/reload", (route) => {
    reloads++;
    expect(route.request().method()).toBe("POST");
    if (reloads === 1)
      return route.fulfill({ status: 500, json: { detail: "Reload failed" } });
    corrected = true;
    return route.fulfill({ json: { success: true, scope: "shared_config" } });
  });
  await page.goto("/workspace/capabilities?tab=skills");
  await expect(
    page.getByRole("heading", { name: "Could not load" }),
  ).toBeVisible();
  await expect(page.getByText("collect-startrun/SKILL.md:3:27")).toBeVisible();
  await expect(
    page.getByText("Quote values containing a colon followed by a space."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "View details collect-startrun" }),
  ).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("skill-yaml-warning.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Reload skills", exact: true })
    .click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Could not reload skills. Try again." }),
  ).toBeVisible();
  await expect(page.getByText("collect-startrun/SKILL.md:3:27")).toBeVisible();
  await page
    .getByRole("button", { name: "Reload skills", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Could not load" }),
  ).toHaveCount(0);
  await page.getByRole("tab", { name: "My skills", exact: true }).click();
  await expect(
    page.getByRole("button", {
      name: "View details collect-startrun",
      exact: true,
    }),
  ).toBeVisible();
});

test("ordinary users never request management diagnostics", async ({
  page,
}) => {
  mockLangGraphAPI(page, { skills: [] });
  let requests = 0;
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      json: {
        id: "ordinary",
        email: "ordinary@example.com",
        system_role: "user",
        needs_setup: false,
        permissions: [],
      },
    }),
  );
  await page.route("**/api/skills/diagnostics/custom", (route) => {
    requests++;
    return route.fulfill({ json: { diagnostics: [] } });
  });
  // The local preview starts with an SSR admin. Refresh the real auth
  // provider before opening the skill gallery as an ordinary user.
  await page.goto("/workspace/capabilities");
  await expect(
    page.getByRole("textbox", { name: "Search plugins by name or purpose" }),
  ).toBeEnabled();
  const refreshed = page.waitForResponse("**/api/v1/auth/me");
  await page.evaluate(() =>
    document.dispatchEvent(new Event("visibilitychange")),
  );
  await refreshed;
  await page.getByRole("tab", { name: "Skills", exact: true }).click();
  await expect(
    page.getByRole("tab", { name: "My skills", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reload skills", exact: true }),
  ).toHaveCount(0);
  expect(requests).toBe(0);
});
