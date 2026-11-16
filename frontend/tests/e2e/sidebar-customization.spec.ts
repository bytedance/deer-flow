import { expect, test, type Locator, type Page } from "@playwright/test";

import { LOCAL_SETTINGS_KEY } from "../../src/core/settings/local";

import { mockLangGraphAPI } from "./utils/mock-api";

const sidebar = (page: Page) => page.locator("[data-sidebar='sidebar']");
const navButtons = (page: Page) =>
  sidebar(page)
    .locator('[data-workspace-nav="true"]')
    .locator("[data-sidebar='menu-button']");

const LAYOUTS = {
  usageInMore: {
    version: 1,
    primary: ["search", "agents", "scheduled-tasks", "capabilities"],
    more: ["usage"],
  },
  searchInMore: {
    version: 1,
    primary: ["agents", "scheduled-tasks", "usage", "capabilities"],
    more: ["search"],
  },
};

async function seedLayout(page: Page, layout: unknown) {
  await page.addInitScript(
    ([key, value]) => {
      localStorage.setItem(key, JSON.stringify({ navLayout: value }));
    },
    [LOCAL_SETTINGS_KEY, layout] as const,
  );
}

async function navLabels(page: Page): Promise<string[]> {
  return navButtons(page).evaluateAll((buttons) =>
    buttons.map((button) => button.querySelector("span")?.textContent ?? ""),
  );
}

const customizeDialog = (page: Page) =>
  page
    .getByRole("dialog")
    .filter({ has: page.getByRole("heading", { name: "Customize menu" }) });

async function openCustomizeDialog(page: Page) {
  await sidebar(page)
    .getByRole("button", { name: "More", exact: true })
    .click();
  await page.getByRole("menuitem", { name: "Customize menu" }).click();
  const dialog = customizeDialog(page);
  await expect(dialog).toBeVisible();
  return dialog;
}

async function dragByHandle(
  page: Page,
  handle: Locator,
  target: Locator,
): Promise<void> {
  const from = await handle.boundingBox();
  const to = await target.boundingBox();
  if (!from || !to) throw new Error("drag source or target is not visible");
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    from.x + from.width / 2 + 12,
    from.y + from.height / 2 + 12,
    { steps: 4 },
  );
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, {
    steps: 12,
  });
  await page.mouse.up();
}

test.describe("sidebar customization", () => {
  test("keeps chats first and puts More last by default", async ({ page }) => {
    mockLangGraphAPI(page, { threads: [] });
    await page.goto("/workspace/chats/new");

    await expect(navButtons(page).first()).toContainText("Chats");
    await expect(navButtons(page).nth(1)).toContainText("Search");
    await expect(navButtons(page).last()).toContainText("More");
  });

  test("drags an entry into More, hides it from the menu, and survives a reload", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: [] });
    await page.goto("/workspace/chats/new");
    await expect(navButtons(page).first()).toContainText("Chats");

    const dialog = await openCustomizeDialog(page);
    await dragByHandle(
      page,
      dialog.getByRole("button", { name: "Reorder Token usage" }),
      dialog.locator('[data-group="more"]'),
    );
    await expect(dialog.locator('[data-group="more"]')).toContainText(
      "Token usage",
    );

    await page.keyboard.press("Escape");
    await expect(customizeDialog(page)).toHaveCount(0);
    expect(await navLabels(page)).not.toContain("Token usage");

    await page.reload();
    await expect(navButtons(page).first()).toContainText("Chats");
    await expect.poll(() => navLabels(page)).not.toContain("Token usage");

    await sidebar(page)
      .getByRole("button", { name: "More", exact: true })
      .click();
    await expect(
      page.getByRole("menuitem", { name: "Token usage" }),
    ).toBeVisible();
  });

  test("drags an entry back from More into the menu", async ({ page }) => {
    await seedLayout(page, LAYOUTS.usageInMore);
    mockLangGraphAPI(page, { threads: [] });
    await page.goto("/workspace/chats/new");
    await expect(navButtons(page).first()).toContainText("Chats");
    await expect.poll(() => navLabels(page)).not.toContain("Token usage");

    const dialog = await openCustomizeDialog(page);
    await dragByHandle(
      page,
      dialog.getByRole("button", { name: "Reorder Token usage" }),
      dialog.getByText("Capability Center", { exact: true }),
    );
    await expect(dialog.locator('[data-group="primary"]')).toContainText(
      "Token usage",
    );

    await page.keyboard.press("Escape");
    await expect(customizeDialog(page)).toHaveCount(0);
    await expect.poll(() => navLabels(page)).toContain("Token usage");
  });

  test("reorders entries inside the menu group", async ({ page }) => {
    mockLangGraphAPI(page, { threads: [] });
    await page.goto("/workspace/chats/new");
    await expect(navButtons(page).first()).toContainText("Chats");

    const dialog = await openCustomizeDialog(page);
    await dragByHandle(
      page,
      dialog.getByRole("button", { name: "Reorder Capability Center" }),
      dialog.getByText("Search", { exact: true }),
    );

    await page.keyboard.press("Escape");
    await expect(customizeDialog(page)).toHaveCount(0);
    await expect
      .poll(() => navLabels(page))
      .toEqual([
        "Chats",
        "Capability Center",
        "Search",
        "Agents",
        "Scheduled tasks",
        "Token usage",
        "More",
      ]);
  });

  test("navigates to an entry that was moved into More", async ({ page }) => {
    await seedLayout(page, LAYOUTS.usageInMore);
    mockLangGraphAPI(page, { threads: [] });
    await page.goto("/workspace/chats/new");
    await expect(navButtons(page).first()).toContainText("Chats");
    await expect.poll(() => navLabels(page)).not.toContain("Token usage");

    await sidebar(page)
      .getByRole("button", { name: "More", exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Token usage" }).click();

    await expect(page).toHaveURL(/\/workspace\/usage/);
  });

  test("navigates to scheduled tasks from More", async ({ page }) => {
    await seedLayout(page, {
      version: 1,
      primary: ["search", "agents", "usage", "capabilities"],
      more: ["scheduled-tasks"],
    });
    mockLangGraphAPI(page, { threads: [] });
    await page.goto("/workspace/chats/new");
    await expect(navButtons(page).first()).toContainText("Chats");
    await expect.poll(() => navLabels(page)).not.toContain("Scheduled tasks");

    await sidebar(page)
      .getByRole("button", { name: "More", exact: true })
      .click();
    await page.getByRole("menuitem", { name: "Scheduled tasks" }).click();

    await expect(page).toHaveURL(/\/workspace\/scheduled-tasks/);
  });

  test("shows a disabled entry in More as greyed out with its reason", async ({
    page,
  }) => {
    await seedLayout(page, {
      version: 1,
      primary: ["search", "scheduled-tasks", "usage", "capabilities"],
      more: ["agents"],
    });
    mockLangGraphAPI(page, {
      threads: [],
      features: { agentsApiEnabled: false },
    });
    await page.goto("/workspace/chats/new");
    await expect(navButtons(page).first()).toContainText("Chats");
    await expect.poll(() => navLabels(page)).not.toContain("Agents");

    await sidebar(page)
      .getByRole("button", { name: "More", exact: true })
      .click();
    const agents = page.getByRole("menuitem", {
      name: "Agents",
      exact: true,
    });
    await expect(agents).toHaveAttribute("aria-disabled", "true");
    await expect(agents).toHaveClass(/text-muted-foreground\/50/);

    await agents.hover();
    await expect(page.getByRole("tooltip")).toContainText(
      "Feature not enabled",
    );
  });

  test("greys out a feature-disabled entry in the customization dialog", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [],
      features: { agentsApiEnabled: false },
    });
    await page.goto("/workspace/chats/new");
    await expect(navButtons(page).first()).toContainText("Chats");

    const dialog = await openCustomizeDialog(page);
    const agents = dialog.getByText("Agents", { exact: true });
    await expect(agents).toHaveClass(/text-muted-foreground\/50/);
    await agents.hover();
    await expect(page.getByRole("tooltip")).toContainText(
      "Feature not enabled",
    );
  });

  test("moves an entry into the menu at the first position", async ({
    page,
  }) => {
    await seedLayout(page, LAYOUTS.usageInMore);
    mockLangGraphAPI(page, { threads: [] });
    await page.goto("/workspace/chats/new");
    await expect(navButtons(page).first()).toContainText("Chats");
    await expect.poll(() => navLabels(page)).not.toContain("Token usage");

    const dialog = await openCustomizeDialog(page);
    await dragByHandle(
      page,
      dialog.getByRole("button", { name: "Reorder Token usage" }),
      dialog.getByText("Chats", { exact: true }),
    );

    await page.keyboard.press("Escape");
    await expect(customizeDialog(page)).toHaveCount(0);
    await expect
      .poll(() => navLabels(page))
      .toEqual([
        "Token usage",
        "Chats",
        "Search",
        "Agents",
        "Scheduled tasks",
        "Capability Center",
        "More",
      ]);
  });

  test("moves an entry into a non-empty More at the drop position", async ({
    page,
  }) => {
    await seedLayout(page, LAYOUTS.usageInMore);
    mockLangGraphAPI(page, { threads: [] });
    await page.goto("/workspace/chats/new");
    await expect(navButtons(page).first()).toContainText("Chats");
    await expect.poll(() => navLabels(page)).not.toContain("Token usage");

    const dialog = await openCustomizeDialog(page);
    await dragByHandle(
      page,
      dialog.getByRole("button", { name: "Reorder Search" }),
      dialog.getByText("Token usage", { exact: true }),
    );
    await expect(
      dialog.locator('[data-group="more"]').getByRole("listitem"),
    ).toHaveText(["Search", "Token usage"]);

    await page.keyboard.press("Escape");
    await expect(customizeDialog(page)).toHaveCount(0);
    expect(await navLabels(page)).not.toContain("Search");

    await sidebar(page)
      .getByRole("button", { name: "More", exact: true })
      .click();
    await expect(page.getByRole("menuitem").nth(0)).toContainText("Search");
    await expect(page.getByRole("menuitem").nth(1)).toContainText(
      "Token usage",
    );
  });

  test("leaves the layout unchanged when a keyboard drag is cancelled", async ({
    page,
  }) => {
    await seedLayout(page, LAYOUTS.usageInMore);
    mockLangGraphAPI(page, { threads: [] });
    await page.goto("/workspace/chats/new");
    await expect(navButtons(page).first()).toContainText("Chats");
    await expect.poll(() => navLabels(page)).not.toContain("Token usage");

    const dialog = await openCustomizeDialog(page);
    const handle = dialog.getByRole("button", {
      name: "Reorder Token usage",
    });
    await handle.focus();
    await page.keyboard.press("Space");
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("Escape");

    await expect(customizeDialog(page)).toHaveCount(0);
    expect(await navLabels(page)).not.toContain("Token usage");
    const stored = await page.evaluate(
      (key) => localStorage.getItem(key),
      LOCAL_SETTINGS_KEY,
    );
    expect(stored).toContain('"more":["usage"]');
  });

  test("keeps Cmd+K working after search is moved into More", async ({
    page,
  }) => {
    await seedLayout(page, LAYOUTS.searchInMore);
    mockLangGraphAPI(page, { threads: [] });
    await page.goto("/workspace/chats/new");
    await expect(navButtons(page).first()).toContainText("Chats");
    await expect.poll(() => navLabels(page)).not.toContain("Search");

    await page.keyboard.press("Control+K");
    await expect(
      page.getByRole("dialog").getByRole("combobox", {
        name: "Search conversations",
      }),
    ).toBeVisible();
  });

  test("opens the customization dialog from the mobile drawer", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    mockLangGraphAPI(page, { threads: [] });
    await page.goto("/workspace/chats/new");

    const drawer = page.locator("[data-mobile='true'][data-sidebar='sidebar']");
    const toggle = page.getByRole("button", {
      name: "Toggle Sidebar",
      exact: true,
    });
    // The trigger is server-rendered, so a click before hydration does
    // nothing. Retry until the drawer actually opens.
    await expect(async () => {
      if (!(await drawer.isVisible())) {
        await toggle.click();
      }
      await expect(drawer).toBeVisible({ timeout: 1_000 });
    }).toPass({ timeout: 15_000 });
    await expect(
      drawer.getByRole("link", { name: "Chats", exact: true }),
    ).toBeVisible();

    await drawer.getByRole("button", { name: "More", exact: true }).click();
    await page.getByRole("menuitem", { name: "Customize menu" }).click();

    const dialog = customizeDialog(page);
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Chats", { exact: true })).toBeVisible();
  });
});
