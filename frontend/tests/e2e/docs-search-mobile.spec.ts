import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 700 }, hasTouch: true });

for (const lang of ["en", "zh"]) {
  test(`mobile ${lang} search results scroll and same-hash selection closes the menu`, async ({
    page,
    context,
  }) => {
    await page.goto(`/${lang}/docs#result-0`);
    await expect(page.locator("html")).toHaveAttribute(
      "lang",
      lang === "zh" ? "zh-CN" : "en-US",
    );
    // Keep the real Nextra combobox, portal, Radix modal and browser scrolling.
    // Only the search-engine response is deterministic; no generated index is needed.
    await page.evaluate((language) => {
      Object.defineProperty(window, "pagefind", {
        configurable: true,
        value: {
          debouncedSearch: async (
            _query: string,
            options?: { filters?: { lang?: string } },
          ) => ({
            results:
              options?.filters?.lang === language
                ? [
                    {
                      data: async () => ({
                        url: window.location.pathname,
                        meta: { title: "Documentation" },
                        sub_results: Array.from({ length: 40 }, (_, index) => ({
                          url: `${window.location.pathname}#result-${index}`,
                          title: `Result ${index}`,
                          excerpt:
                            "A matching documentation section about sandboxes.",
                        })),
                      }),
                    },
                  ]
                : [],
          }),
        },
      });
    }, lang);

    await page.getByRole("button", { name: "Open menu" }).tap();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox").fill("sandbox");
    const results = page.getByRole("listbox");
    await expect(results.getByRole("option")).toHaveCount(40);
    await expect(results).toBeVisible();
    expect(
      await results.evaluate((panel) =>
        Boolean(panel.closest('[role="dialog"]')),
      ),
    ).toBe(true);

    // Wait for the sheet/anchored panel's opening transition before gestures.
    await results.hover({ position: { x: 20, y: 60 } });
    const bounds = (await results.boundingBox())!;
    await page.mouse.wheel(0, 300);
    await expect
      .poll(() => results.evaluate((panel) => panel.scrollTop))
      .toBeGreaterThan(0);

    const beforeTouch = await results.evaluate((panel) => panel.scrollTop);
    const client = await context.newCDPSession(page);
    const point = {
      x: bounds.x + bounds.width / 2,
      y: bounds.y + bounds.height - 60,
    };
    await client.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [point],
    });
    await client.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ ...point, y: point.y - 150 }],
    });
    await client.send("Input.dispatchTouchEvent", {
      type: "touchEnd",
      touchPoints: [],
    });
    await expect
      .poll(() => results.evaluate((panel) => panel.scrollTop))
      .toBeGreaterThan(beforeTouch);
    await expect(dialog).toBeVisible();

    await results.evaluate((panel) => {
      panel.scrollTop = 0;
    });
    await results.getByRole("option", { name: /^Result 0\b/ }).tap();
    await expect(dialog).toBeHidden();
    await expect(page).toHaveURL(new RegExp(`/${lang}/docs#result-0$`));

    await page.getByRole("button", { name: "Open menu" }).tap();
    const input = dialog.getByRole("combobox");
    await input.fill("sandbox");
    await expect(results.getByRole("option")).toHaveCount(40);
    await input.press("ArrowDown");
    await input.press("Home");
    await expect(input).toHaveAttribute(
      "aria-activedescendant",
      (await results.getByRole("option").first().getAttribute("id"))!,
    );
    await input.press("Enter");
    await expect(dialog).toBeHidden();
    await expect(page).toHaveURL(new RegExp(`/${lang}/docs#result-0$`));
  });
}
