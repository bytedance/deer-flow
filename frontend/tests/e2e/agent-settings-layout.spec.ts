import { expect, test, type Locator, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const description =
  "A general-purpose worker for independent analysis. " +
  "Investigate the delegated question, check the evidence, and report findings to the caller. ".repeat(
    15,
  );

const longName = "research" + "a".repeat(57);
const missingName = "missing" + "b".repeat(58);

async function expectInsideViewport(element: Locator) {
  await expect(element).toBeVisible();
  const bounds = await element.boundingBox();
  const viewport = element.page().viewportSize()!;
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height);
}

async function openSettings(
  page: Page,
  allowedSubagents: string[] | null = null,
) {
  const agent = {
    name: "test-agent",
    model: "test-model",
    thinking_enabled: true,
    reasoning_effort: "high",
    allowed_subagents: allowedSubagents,
  };
  mockLangGraphAPI(page, { agents: [agent] });
  await page.route("**/api/models", (route) =>
    route.fulfill({
      json: {
        models: [
          {
            name: "test-model",
            display_name: "Test model",
            supports_thinking: true,
            supports_reasoning_effort: true,
          },
        ],
      },
    }),
  );
  await page.route("**/api/subagents", (route) =>
    route.fulfill({
      json: {
        subagents: [
          { name: "general-purpose", description, enabled: true },
          { name: "bash", description: "Run shell commands.", enabled: true },
          {
            name: longName,
            description: "A worker with a long name.",
            enabled: true,
          },
        ],
      },
    }),
  );
  let saved: Record<string, unknown> | undefined;
  await page.route("**/api/agents/test-agent", (route) => {
    if (route.request().method() === "PUT") {
      saved = route.request().postDataJSON() as Record<string, unknown>;
      return route.fulfill({ json: { ...agent, ...saved } });
    }
    return route.fulfill({ json: agent });
  });
  await page.goto("/workspace/agents");
  await page.getByTitle("Agent settings", { exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox").last().click();
  await page
    .getByRole("option", { name: "Selected subagents", exact: true })
    .click();
  return { dialog, saved: () => saved };
}

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 640 },
]) {
  test(`agent settings remain usable at ${viewport.width}x${viewport.height}`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport);
    const { dialog, saved } = await openSettings(page);
    await expectInsideViewport(dialog);
    await expectInsideViewport(
      dialog.getByRole("heading", { name: "Agent settings" }),
    );
    await expectInsideViewport(
      dialog.getByRole("button", { name: "Close", exact: true }),
    );
    await expectInsideViewport(
      dialog.getByRole("button", { name: "Save", exact: true }),
    );
    await expectInsideViewport(
      dialog.getByRole("button", { name: "Cancel", exact: true }),
    );

    const general = dialog.getByRole("checkbox", {
      name: "general-purpose",
      exact: true,
    });
    await general.check();
    const details = dialog.locator("details").first();
    const summary = details.locator("summary");
    await summary.scrollIntoViewIfNeeded();
    const preview = summary.locator("span").first();
    for (const lineHeight of [null, "20px"]) {
      if (lineHeight)
        await preview.evaluate((element, value) => {
          element.style.lineHeight = value;
        }, lineHeight);
      const metrics = await preview.evaluate((element) => ({
        height: element.getBoundingClientRect().height,
        lineHeight: parseFloat(getComputedStyle(element).lineHeight),
      }));
      expect(metrics.height).toBeGreaterThan(0);
      expect(metrics.height).toBeLessThanOrEqual(metrics.lineHeight * 2 + 1);
    }
    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(details).toHaveAttribute("open", "");
    await expect(details.locator("p")).toHaveText(description);
    await expect(general).toBeChecked();
    await expectInsideViewport(
      dialog.getByRole("button", { name: "Save", exact: true }),
    );
    await page.keyboard.press("Enter");
    await expect(details).not.toHaveAttribute("open", "");
    await dialog.getByRole("checkbox", { name: "bash", exact: true }).check();
    const screenshotPath = testInfo.outputPath("agent-settings.png");
    await page.screenshot({ path: screenshotPath });
    await testInfo.attach("agent-settings", {
      path: screenshotPath,
      contentType: "image/png",
    });
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(dialog).toBeHidden();
    expect(saved()?.allowed_subagents).toEqual(["general-purpose", "bash"]);
  });

  test(`collapsed descriptions are accessible at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const { dialog } = await openSettings(page);
    const summary = dialog.locator("summary").first();
    await summary.focus();
    await expect(summary).toHaveAccessibleName(
      "general-purpose: Delegation description",
    );
    await expect(summary).toHaveAccessibleDescription(description);
    await expect(summary.locator("..")).not.toHaveAttribute("open", "");
  });

  test(`bottom-edge expansion reveals text at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const { dialog } = await openSettings(page);
    const details = dialog.locator("details").first();
    const summary = details.locator("summary");
    await summary.focus();
    // Reproduce scrolling a focused disclosure to the last eight visible
    // pixels. A locator click would auto-scroll and hide this bug.
    const clickPoint = await summary.evaluate((element) => {
      let scrollArea = element.parentElement!;
      while (getComputedStyle(scrollArea).overflowY !== "auto")
        scrollArea = scrollArea.parentElement!;
      const area = scrollArea.getBoundingClientRect();
      scrollArea.scrollTop +=
        element.getBoundingClientRect().top - (area.bottom - 8);
      const bounds = element.getBoundingClientRect();
      return { x: bounds.x + 5, y: bounds.y + 4 };
    });
    await page.mouse.click(clickPoint.x, clickPoint.y);
    await expect(details).toHaveAttribute("open", "");
    await expect
      .poll(() =>
        details.locator("p").evaluate((paragraph) => {
          let scrollArea = paragraph.parentElement!;
          while (getComputedStyle(scrollArea).overflowY !== "auto")
            scrollArea = scrollArea.parentElement!;
          const area = scrollArea.getBoundingClientRect();
          const bounds = paragraph.getBoundingClientRect();
          return (
            bounds.top >= area.top - 1 &&
            bounds.top + parseFloat(getComputedStyle(paragraph).lineHeight) <=
              area.bottom
          );
        }),
      )
      .toBe(true);
    await expect(summary).toBeFocused();
    await expectInsideViewport(
      dialog.getByRole("button", { name: "Save", exact: true }),
    );
    await page.keyboard.press("Enter");
    await expect(details).not.toHaveAttribute("open", "");
    await expect(
      dialog.getByRole("checkbox", { name: "general-purpose", exact: true }),
    ).not.toBeChecked();
  });

  test(`long worker names wrap at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const { dialog, saved } = await openSettings(page, [missingName]);
    for (const name of [longName, missingName]) {
      const checkbox = dialog.getByRole("checkbox", {
        name: new RegExp(`^${name}`),
      });
      await checkbox.scrollIntoViewIfNeeded();
      await expectInsideViewport(checkbox);
      const metrics = await checkbox.evaluate((element) => {
        const label = element.closest("label")!;
        const nameElement = label.querySelector("span.font-medium")!;
        const bounds = nameElement.getBoundingClientRect();
        const box = element.getBoundingClientRect();
        const labelBounds = label.getBoundingClientRect();
        return {
          nameHeight: bounds.height,
          lineHeight: parseFloat(getComputedStyle(nameElement).lineHeight),
          fits:
            bounds.left >= labelBounds.left &&
            bounds.right <= labelBounds.right + 1,
          checkboxWidth: box.width,
          expectedWidth: parseFloat(getComputedStyle(element).height),
        };
      });
      expect(metrics.nameHeight).toBeGreaterThan(metrics.lineHeight);
      expect(metrics.fits).toBe(true);
      expect(metrics.checkboxWidth).toBeCloseTo(metrics.expectedWidth, 1);
      if (name === longName) {
        await checkbox.check();
      } else {
        // Removing an unavailable selection also removes its row.
        await checkbox.click();
        await expect(checkbox).toHaveCount(0);
      }
    }
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(dialog).toBeHidden();
    expect(saved()?.allowed_subagents).toEqual([longName]);
  });
}
