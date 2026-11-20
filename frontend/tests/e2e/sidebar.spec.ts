import { writeFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test.describe("Sidebar navigation", () => {
  test.describe("collapsed mobile navigation", () => {
    test.use({ hasTouch: true });
    for (const width of [390, 767]) {
      test(`collapsed sidebar remains usable at ${width}px`, async ({
        page,
        context,
        baseURL,
      }) => {
        await context.addCookies([
          { name: "sidebar_state", value: "false", url: baseURL! },
        ]);
        await page.setViewportSize({ width, height: 812 });
        mockLangGraphAPI(page, {
          threads: [
            { thread_id: MOCK_THREAD_ID, title: "Existing conversation" },
          ],
        });
        await page.goto("/workspace/chats/new");
        await expect(page.getByRole("textbox").first()).toBeVisible();

        const screenshot = test
          .info()
          .outputPath("collapsed-mobile-sidebar.png");
        await page.screenshot({ path: screenshot });
        await test.info().attach("collapsed-mobile-sidebar", {
          path: screenshot,
          contentType: "image/png",
        });
        const sidebar = page.locator("[data-sidebar='sidebar']:visible");
        await expect(
          sidebar.locator("a[href='/workspace/chats']"),
        ).toBeVisible();
        await expect(
          sidebar.locator("a[href='/workspace/agents']"),
        ).toBeVisible();
        const trigger = sidebar.locator("[data-sidebar='trigger']");
        await expect(trigger).toBeVisible();
        await expect(trigger).toHaveAttribute("aria-expanded", "false");
        await expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
        await trigger.tap();

        const drawer = page.locator(
          "[data-mobile='true'][data-sidebar='sidebar']",
        );
        await expect(drawer).toBeVisible();
        const drawerTrigger = drawer.locator("[data-sidebar='trigger']");
        await expect(drawerTrigger).toHaveAttribute("aria-expanded", "true");
        await expect(drawerTrigger).toHaveAttribute("aria-haspopup", "dialog");
        await expect(
          drawer.getByText("Existing conversation", { exact: true }),
        ).toBeVisible();
        await expect(
          drawer.getByTestId("projects-display-mode-toggle"),
        ).toBeVisible();
        await expect(
          drawer.getByText("Settings and more", { exact: true }),
        ).toBeVisible();
        await expect(
          page.locator("a[href='/workspace/agents']:visible"),
        ).toHaveCount(1);
        await page.keyboard.press("Escape");

        await expect(drawer).toBeHidden();
        await expect(
          sidebar.locator("a[href='/workspace/agents']"),
        ).toBeVisible();
        await expect(sidebar.locator("[data-sidebar='trigger']")).toBeFocused();
        await expect(
          sidebar.locator("[data-sidebar='trigger']"),
        ).toHaveAttribute("aria-expanded", "false");
        await expect
          .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
          .toBeLessThanOrEqual(width);
        expect(
          (await context.cookies()).find(
            (cookie) => cookie.name === "sidebar_state",
          )?.value,
        ).toBe("false");

        await sidebar.locator("a[href='/workspace/agents']").tap();
        await expect(page).toHaveURL(/\/workspace\/agents$/);
        await page.setViewportSize({ width: 768, height: 812 });
        await expect(
          page.locator("[data-slot='sidebar'][data-state='collapsed']"),
        ).toBeVisible();
        await expect(
          page.locator("[data-mobile='true'][data-sidebar='sidebar']"),
        ).toBeHidden();
      });
    }

    test("mobile drawer closes after tapping a navigation link", async ({
      page,
      context,
      baseURL,
    }) => {
      await context.addCookies([
        { name: "sidebar_state", value: "false", url: baseURL! },
      ]);
      await page.setViewportSize({ width: 390, height: 812 });
      mockLangGraphAPI(page);
      await page.goto("/workspace/chats/new");
      await expect(page.getByRole("textbox").first()).toBeVisible();

      const sidebar = page.locator("[data-sidebar='sidebar']:visible");
      await sidebar.locator("[data-sidebar='trigger']").tap();
      const drawer = page.locator(
        "[data-mobile='true'][data-sidebar='sidebar']",
      );
      await expect(drawer).toBeVisible();

      await drawer.locator("a[href='/workspace/agents']").tap();
      await expect(page).toHaveURL(/\/workspace\/agents$/);
      await expect(drawer).toBeHidden();
      await expect(sidebar.locator("a[href='/workspace/chats']")).toBeVisible();
      await expect(sidebar.locator("[data-sidebar='trigger']")).toHaveAttribute(
        "aria-expanded",
        "false",
      );

      await sidebar.locator("a[href='/workspace/chats']").tap();
      await expect(page).toHaveURL(/\/workspace\/chats$/);
      expect(
        (await context.cookies()).find(
          (cookie) => cookie.name === "sidebar_state",
        )?.value,
      ).toBe("false");
    });

    for (const preference of ["false", "true"]) {
      test(`chat header reflects the drawer state and restores focus with sidebar_state=${preference}`, async ({
        page,
        context,
        baseURL,
      }) => {
        await context.addCookies([
          { name: "sidebar_state", value: preference, url: baseURL! },
        ]);
        await page.setViewportSize({ width: 390, height: 812 });
        mockLangGraphAPI(page);
        await page.goto("/workspace/chats/new");
        await expect(page.getByRole("textbox").first()).toBeVisible();

        const pageTrigger = page.locator("header [data-sidebar='trigger']");
        await expect(pageTrigger).toHaveAttribute("aria-expanded", "false");
        await expect(pageTrigger).toHaveAttribute("aria-haspopup", "dialog");
        await expect(
          pageTrigger.locator(".lucide-panel-left-open"),
        ).toBeVisible();
        await pageTrigger.tap();

        const drawer = page.getByRole("dialog", { name: "Sidebar" });
        const drawerTrigger = drawer.locator("[data-sidebar='trigger']");
        await expect(drawerTrigger).toHaveAttribute("aria-expanded", "true");
        await expect(
          drawerTrigger.locator(".lucide-panel-left-close"),
        ).toBeVisible();
        await drawerTrigger.tap();
        await expect(drawer).toHaveCount(0);
        await expect(pageTrigger).toBeFocused();
        await expect(pageTrigger).toHaveAttribute("aria-expanded", "false");

        await pageTrigger.tap();
        await expect(drawer).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(drawer).toHaveCount(0);
        await expect(pageTrigger).toBeFocused();
      });

      test(`drawer navigation preserves Chats search focus with sidebar_state=${preference}`, async ({
        page,
        context,
        baseURL,
      }) => {
        await context.addCookies([
          { name: "sidebar_state", value: preference, url: baseURL! },
        ]);
        await page.setViewportSize({ width: 390, height: 812 });
        mockLangGraphAPI(page);
        await page.goto("/workspace/chats/new");
        await expect(page.getByRole("textbox").first()).toBeVisible();
        const pageTrigger = page.locator("header [data-sidebar='trigger']");
        await pageTrigger.tap();
        const drawer = page.getByRole("dialog", { name: "Sidebar" });
        await drawer.locator("a[href='/workspace/chats']").tap();
        await expect(page).toHaveURL(/\/workspace\/chats$/);
        await expect(drawer).toHaveCount(0);
        const search = page.getByRole("searchbox");
        await expect(search).toBeFocused();
        await page.keyboard.type("Find a conversation");
        await expect(search).toHaveValue("Find a conversation");
      });
    }
  });

  test.describe("Agents gallery header", () => {
    for (const width of [390, 767, 1280]) {
      test.describe(`${width}px`, () => {
        test.use({ hasTouch: width < 768 });

        for (const preference of ["false", "true"]) {
          test(`keeps header actions usable with sidebar_state=${preference}`, async ({
            page,
            context,
            baseURL,
          }) => {
            await context.addCookies([
              { name: "sidebar_state", value: preference, url: baseURL! },
            ]);
            await page.setViewportSize({ width, height: 812 });
            mockLangGraphAPI(page);
            await page.goto("/workspace/agents");
            if (width < 768 && preference === "false") {
              await expect(
                page.locator(
                  "[data-sidebar='sidebar'][data-collapsible='icon']:visible",
                ),
              ).toBeVisible();
            }

            const title = page.getByRole("heading", { level: 1 });
            const description = title.locator("..").locator("p");
            const importButton = page.getByRole("button", {
              name: "Import Agent",
              exact: true,
            });
            const newAgentButtons = page.getByRole("button", {
              name: "New Agent",
              exact: true,
            });
            const headerNewAgentButton = newAgentButtons.first();
            await expect(title).toBeVisible();
            // The mocked empty gallery also exposes a second New Agent button.
            await expect(newAgentButtons).toHaveCount(2);
            await page.evaluate(() =>
              document.fonts.ready.then(() => undefined),
            );

            try {
              const content = await page
                .locator("[data-slot='sidebar-inset']")
                .boundingBox();
              expect(content).not.toBeNull();
              const elements = [
                { name: "title", locator: title },
                { name: "description", locator: description },
                { name: "import", locator: importButton },
                { name: "newAgent", locator: headerNewAgentButton },
              ];
              const geometry = await Promise.all(
                elements.map(async ({ name, locator }) => ({
                  name,
                  box: await locator.boundingBox(),
                })),
              );
              const geometryPath = test
                .info()
                .outputPath(`agents-header-${width}-${preference}.json`);
              await writeFile(
                geometryPath,
                JSON.stringify({
                  viewport: width,
                  documentWidth: await page.evaluate(
                    () => document.documentElement.scrollWidth,
                  ),
                  content,
                  elements: geometry,
                }),
                "utf8",
              );
              await test.info().attach("agents-header-geometry", {
                path: geometryPath,
                contentType: "application/json",
              });
              for (const { locator } of elements) {
                await expect(locator).toBeVisible();
                const box = await locator.boundingBox();
                expect(box).not.toBeNull();
                expect(box!.x).toBeGreaterThanOrEqual(content!.x - 1);
                expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
              }
              await expect
                .poll(() =>
                  page.evaluate(() => document.documentElement.scrollWidth),
                )
                .toBeLessThanOrEqual(width);
              if (width === 390) {
                const descriptionBox = await description.boundingBox();
                // A fully visible but word-wide description is still unusable.
                expect(descriptionBox!.width).toBeGreaterThan(width / 2);
              }
            } finally {
              const screenshot = test
                .info()
                .outputPath(`agents-header-${width}-${preference}.png`);
              await page.screenshot({
                path: screenshot,
                animations: "disabled",
              });
              await test.info().attach("agents-header", {
                path: screenshot,
                contentType: "image/png",
              });
            }

            const fileChooserOpened = page.waitForEvent("filechooser");
            if (width < 768) {
              await importButton.tap();
            } else {
              await importButton.click();
            }
            const fileChooser = await fileChooserOpened;
            await fileChooser.setFiles([]);
            expect(
              (await context.cookies()).find(
                (cookie) => cookie.name === "sidebar_state",
              )?.value,
            ).toBe(preference);

            if (width < 768) {
              await headerNewAgentButton.tap();
            } else {
              await headerNewAgentButton.click();
            }
            await expect(page).toHaveURL(/\/workspace\/agents\/new$/);
          });
        }
      });
    }
  });

  test("sidebar contains Chats and Agents nav links", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    // Sidebar uses data-sidebar="menu-button" with asChild rendering on <Link>
    const sidebar = page.locator("[data-sidebar='sidebar']");
    await expect(sidebar.locator("a[href='/workspace/chats']")).toBeVisible({
      timeout: 15_000,
    });
    await expect(sidebar.locator("a[href='/workspace/agents']")).toBeVisible();
  });

  test("Agents link navigates to agents page", async ({ page }) => {
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    const agentsLink = sidebar.locator("a[href='/workspace/agents']");
    await expect(agentsLink).toBeVisible({ timeout: 15_000 });
    await agentsLink.click();

    await page.waitForURL("**/workspace/agents");
    await expect(page).toHaveURL(/\/workspace\/agents/);
  });

  test("Agents button is disabled with a hover tooltip when agents_api is off", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await page.route("**/api/features", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ agents_api: { enabled: false } }),
      }),
    );

    await page.goto("/workspace/chats/new");

    const sidebar = page.locator("[data-sidebar='sidebar']");
    // Chats remains a real link; Agents is no longer a navigable link.
    await expect(sidebar.locator("a[href='/workspace/chats']")).toBeVisible({
      timeout: 15_000,
    });
    await expect(sidebar.locator("a[href='/workspace/agents']")).toHaveCount(0);

    // The disabled Agents button is rendered and announces its disabled state.
    const agentsButton = sidebar.getByRole("button", { name: "Agents" });
    await expect(agentsButton).toHaveAttribute("aria-disabled", "true");

    // The button itself has pointer-events suppressed; force the hover so the
    // event reaches the wrapping tooltip-trigger span that surfaces the tooltip.
    await agentsButton.hover({ force: true });
    await expect(page.getByText("Feature not enabled").first()).toBeVisible({
      timeout: 5_000,
    });

    // Keyboard/screen-reader users get the reason too: the disabled entry
    // stays in the tab order (focusable) and is wired to a visually-hidden
    // description rather than relying on the hover-only tooltip.
    const describedById = await agentsButton.getAttribute("aria-describedby");
    expect(describedById).toBeTruthy();
    await expect(page.locator(`#${describedById}`)).toHaveText(
      "Feature not enabled",
    );
    await agentsButton.focus();
    await expect(agentsButton).toBeFocused();
  });

  test("mobile welcome layout stays within viewport and opens sidebar", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 664 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");
    await page.evaluate(() => {
      document.cookie = "locale=zh-CN; path=/; SameSite=Lax";
    });
    await page.reload();

    const viewportWidth = page.viewportSize()?.width ?? 390;
    const expectInsideViewport = async (
      locator: ReturnType<typeof page.locator>,
    ) => {
      await expect(locator).toBeVisible({ timeout: 15_000 });
      const box = await locator.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(-1);
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewportWidth + 1);
    };

    await expectInsideViewport(page.getByText(/欢迎使用 🦌 DeerFlow/).first());
    await expectInsideViewport(page.getByRole("textbox").first());
    await expectInsideViewport(page.locator("[data-slot='suggestions-list']"));

    const mobileSidebarTrigger = page
      .locator("[data-sidebar='trigger']:visible")
      .first();
    await expect(mobileSidebarTrigger).toBeVisible();
    const triggerBox = await mobileSidebarTrigger.boundingBox();
    expect(triggerBox).not.toBeNull();
    const triggerReceivesPointerEvents = await page.evaluate(
      ({ x, y }) => {
        const trigger = document.elementFromPoint(x, y);
        return trigger?.closest("[data-sidebar='trigger']") !== null;
      },
      {
        x: triggerBox!.x + triggerBox!.width / 2,
        y: triggerBox!.y + triggerBox!.height / 2,
      },
    );
    expect(triggerReceivesPointerEvents).toBe(true);
    await page.mouse.click(
      triggerBox!.x + triggerBox!.width / 2,
      triggerBox!.y + triggerBox!.height / 2,
    );

    const mobileSidebar = page.locator(
      "[data-mobile='true'][data-sidebar='sidebar']",
    );
    await expect(mobileSidebar).toBeVisible();
    await expect(
      mobileSidebar.locator("a[href='/workspace/chats']"),
    ).toBeVisible();
    await expect(
      mobileSidebar.locator("a[href='/workspace/agents']"),
    ).toBeVisible();
  });
});
