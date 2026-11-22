import { expect, type Page, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

async function openSkillsAsMockUser(page: Page, waitForCreate = false) {
  await page.goto("/workspace/capabilities");
  await page.getByRole("tab", { name: "Skills", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: /name or purpose/ }),
  ).toBeEnabled();
  if (waitForCreate) {
    await expect(
      page.getByRole("button", { name: "Create skill" }),
    ).toBeVisible();
  }
  const refreshed = page.waitForResponse("**/api/v1/auth/me");
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await refreshed;
}

test.describe("Skill gallery", () => {
  test("shows a failure and keeps the toggle state when disabling a skill is rejected", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      skills: [
        {
          name: "toggle-skill",
          description: "Test skill",
          category: "public",
          enabled: true,
        },
      ],
    });

    void page.route("**/api/suggestions/config", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ enabled: false }),
      });
    });

    void page.route("**/api/skills/toggle-skill", (route) => {
      if (route.request().method() === "PUT") {
        return route.fulfill({
          status: 403,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Skill toggle denied" }),
        });
      }
      return route.fallback();
    });

    await page.goto("/workspace/capabilities?tab=skills");
    const toggle = page.getByRole("switch", { name: /toggle-skill/ });

    await expect(page.getByText("toggle-skill")).toBeVisible();
    await expect(toggle).toBeChecked();
    await toggle.click();

    await expect(page.getByText("Skill toggle denied")).toBeVisible();
    await expect(toggle).toBeChecked();
  });

  test("keeps the old admin entry when the capability block is absent", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await page.goto("/workspace/capabilities?tab=skills");
    await expect(
      page.getByRole("button", { name: "Install skill", exact: true }),
    ).toBeVisible();
  });

  for (const skillManagement of [undefined, null] as const) {
    test(`does not grant an old-backend entry to non-admin users (${String(skillManagement)})`, async ({
      page,
    }) => {
      mockLangGraphAPI(page, {
        systemRole: "user",
        permissions: ["skills:manage"],
        features: { skillManagement },
      });
      await openSkillsAsMockUser(page);
      await expect(
        page.getByRole("button", { name: "Install skill", exact: true }),
      ).toHaveCount(0);
    });
  }

  test("allows an authorized non-admin to manage only their custom skills", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      systemRole: "user",
      permissions: ["skills:manage"],
      skills: [
        {
          name: "public-demo",
          description: "Public",
          category: "public",
          enabled: true,
        },
        {
          name: "custom-demo",
          description: "Custom",
          category: "custom",
          enabled: true,
          editable: true,
        },
      ],
      features: {
        skillManagement: {
          lifecyclePermissions: true,
          canManage: true,
          sourceInstallAvailable: false,
        },
      },
    });
    await page.route("**/api/skills/custom/custom-demo", (route) =>
      route.fulfill({
        json: {
          name: "custom-demo",
          description: "Custom",
          category: "custom",
          license: "",
          enabled: true,
          editable: true,
          content: "---\nname: custom-demo\n---\nCustom instructions",
        },
      }),
    );
    await openSkillsAsMockUser(page, true);

    await expect(
      page.getByRole("button", { name: "Install skill", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("switch", { name: /public-demo/ }),
    ).toBeDisabled();
    await page.getByRole("tab", { name: "My skills", exact: true }).click();
    await expect(
      page.getByRole("switch", { name: /custom-demo/ }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "View details custom-demo", exact: true })
      .click();
    await expect(page.getByText("Custom instructions")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Edit skill" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Export", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Delete skill" }),
    ).toBeVisible();
  });

  test("honors an explicit admin denial for custom but not public skills", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      skills: [
        {
          name: "public-demo",
          description: "Public",
          category: "public",
          enabled: true,
        },
        {
          name: "custom-demo",
          description: "Custom",
          category: "custom",
          enabled: true,
          editable: true,
        },
      ],
      features: {
        skillManagement: {
          lifecyclePermissions: true,
          canManage: false,
          sourceInstallAvailable: true,
        },
      },
    });
    await page.goto("/workspace/capabilities?tab=skills");
    await expect(
      page.getByRole("button", { name: "Install skill", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("switch", { name: /public-demo/ }),
    ).toBeEnabled();
    await page.getByRole("tab", { name: "My skills", exact: true }).click();
    await expect(page.getByRole("switch", { name: /custom-demo/ })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("button", {
        name: "View details custom-demo",
        exact: true,
      }),
    ).toHaveCount(0);
    await page.getByRole("tab", { name: "Community", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Install skill", exact: true }),
    ).toHaveCount(0);
  });

  test("keeps file upload but hides source when the deployment lacks it", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      features: {
        skillManagement: {
          lifecyclePermissions: true,
          canManage: true,
          sourceInstallAvailable: false,
        },
      },
    });
    await page.goto("/workspace/capabilities?tab=skills");
    await page
      .getByRole("button", { name: "Install skill", exact: true })
      .click();
    await expect(
      page.getByRole("menuitem", { name: "From .skill file" }),
    ).toBeVisible();
    await expect(
      page.getByRole("menuitem", { name: "From source" }),
    ).toHaveCount(0);
  });

  test("previews and installs a source with the digest and CSRF token", async ({
    page,
    baseURL,
  }) => {
    mockLangGraphAPI(page, {
      skills: [],
      features: {
        skillManagement: {
          lifecyclePermissions: true,
          canManage: true,
          sourceInstallAvailable: true,
        },
      },
    });
    await page
      .context()
      .addCookies([
        { name: "csrf_token", value: "source-test-token", url: baseURL! },
      ]);
    const preview = {
      source: "owner/repo@demo",
      source_url: "https://skills.sh/owner/repo/demo",
      skill_name: "demo",
      description: "Source demo",
      snapshot_digest: "a".repeat(64),
      upstream_hash: null,
      file_count: 1,
      total_bytes: 42,
    };
    await page.route("**/api/skills/install/source/inspect", async (route) => {
      expect(route.request().headers()["x-csrf-token"]).toBe(
        "source-test-token",
      );
      expect(route.request().postDataJSON()).toEqual({
        source: preview.source,
      });
      await route.fulfill({ json: preview });
    });
    await page.route("**/api/skills/install/source", async (route) => {
      expect(route.request().headers()["x-csrf-token"]).toBe(
        "source-test-token",
      );
      expect(route.request().postDataJSON()).toEqual({
        source: preview.source,
        expected_snapshot_digest: preview.snapshot_digest,
      });
      await route.fulfill({
        json: {
          success: true,
          skill_name: "demo",
          message: "Installed",
          enabled: true,
        },
      });
    });

    await page.goto("/workspace/capabilities?tab=skills");
    await page
      .getByRole("button", { name: "Install skill", exact: true })
      .click();
    await page.getByRole("menuitem", { name: "From source" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Skill source").fill(preview.source);
    await dialog.getByRole("button", { name: "Preview skill" }).click();
    await expect(dialog.getByText("Source demo")).toBeVisible();
    await expect(dialog.getByText(preview.snapshot_digest)).toBeVisible();
    await dialog
      .getByRole("button", { name: "Install skill", exact: true })
      .click();

    await expect(
      dialog.getByText("Skill installed", { exact: true }),
    ).toBeVisible();
    await expect(dialog.getByText(/takes effect immediately/)).toBeVisible();
    await expect(dialog.getByText(/visibility policy/)).toBeVisible();
    await expect(dialog.getByRole("switch", { name: /demo/ })).toBeChecked();
    await expect(
      dialog.getByRole("button", { name: "Delete skill" }),
    ).toBeVisible();
  });
});
