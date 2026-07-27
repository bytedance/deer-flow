import { type Locator, type Page, expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const ARTIFACT_PATH = "/artifact-fixtures/report.html";
const THREAD_ID = "00000000-0000-0000-0000-000000003125";

function writeFileMessages() {
  return [
    {
      type: "human",
      id: "msg-human-artifact",
      content: [{ type: "text", text: "Create a report artifact" }],
    },
    {
      type: "ai",
      id: "msg-ai-write-artifact",
      content: "",
      tool_calls: [
        {
          id: "write-file-artifact",
          name: "write_file",
          args: {
            description: "Writing report artifact",
            path: ARTIFACT_PATH,
            content:
              "<!doctype html><html><body><h1>Report draft</h1></body></html>",
          },
        },
      ],
    },
    {
      type: "tool",
      id: "msg-tool-write-artifact",
      name: "write_file",
      tool_call_id: "write-file-artifact",
      content: "OK",
    },
  ];
}

async function panelWidth(panel: Locator): Promise<number> {
  const box = await panel.boundingBox();
  return box?.width ?? 0;
}

/** Drag the divider left by `distance` px, widening the right panel. */
async function widenPanel(handle: Locator, distance: number): Promise<void> {
  // hover() waits for a stable bounding box: the open animation moves the
  // 1px-wide divider, so coordinates read any earlier miss it entirely.
  await handle.hover();
  await expect(handle).toHaveAttribute("data-separator", "hover");

  const box = await handle.boundingBox();
  expect(box).not.toBeNull();
  const y = box!.y + box!.height / 2;
  const x = box!.x + box!.width / 2;

  const mouse = handle.page().mouse;
  await mouse.down();
  await expect(handle).toHaveAttribute("data-separator", "active");
  await mouse.move(x - distance, y, { steps: 10 });
  await mouse.up();
}

async function openArtifact(page: Page): Promise<void> {
  await expect(page.getByText(ARTIFACT_PATH)).toBeVisible({ timeout: 15_000 });
  await page.getByText(ARTIFACT_PATH).click();
}

test.describe("Artifacts panel resize", () => {
  test.beforeEach(async ({ page }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: THREAD_ID,
          title: "Artifact panel resize",
          messages: writeFileMessages(),
        },
      ],
    });
    await page.goto(`/workspace/chats/${THREAD_ID}`);
  });

  test("the divider resizes the artifacts panel", async ({ page }) => {
    await openArtifact(page);

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel).toBeVisible();

    const handle = page.locator('[data-slot="resizable-handle"]');
    await expect(handle).toBeVisible();
    await handle.hover();

    const widthBefore = await panelWidth(artifactsPanel);
    expect(widthBefore).toBeGreaterThan(0);

    await widenPanel(handle, 200);

    await expect
      .poll(async () => panelWidth(artifactsPanel))
      .toBeGreaterThan(widthBefore + 100);
  });

  test("a dragged width is kept when the panel is reopened", async ({
    page,
  }) => {
    await openArtifact(page);

    const artifactsPanel = page.locator("#artifacts");
    await expect(artifactsPanel).toBeVisible();

    const handle = page.locator('[data-slot="resizable-handle"]');
    await handle.hover();
    const widthBefore = await panelWidth(artifactsPanel);
    await widenPanel(handle, 200);
    await expect
      .poll(async () => panelWidth(artifactsPanel))
      .toBeGreaterThan(widthBefore + 100);
    const widthAfterDrag = await panelWidth(artifactsPanel);

    await artifactsPanel
      .getByRole("button", { name: /close/i })
      .first()
      .click();
    await expect(artifactsPanel).toBeHidden();

    await openArtifact(page);
    await expect(artifactsPanel).toBeVisible();

    await expect
      .poll(async () => panelWidth(artifactsPanel))
      .toBeGreaterThan(widthAfterDrag - 20);
  });
  test("opening animates the width, dragging does not", async ({ page }) => {
    await expect(page.getByText(ARTIFACT_PATH)).toBeVisible({
      timeout: 15_000,
    });

    // Listen for the transition instead of sampling widths: `transitionrun`
    // fires when the transition is created, so a loaded machine dropping
    // frames cannot turn a real animation into a missed one.
    await page.evaluate(() => {
      const store = window as unknown as { __transitions?: string[] };
      store.__transitions = [];
      document.addEventListener(
        "transitionrun",
        (event) => {
          store.__transitions?.push(event.propertyName);
        },
        true,
      );
    });

    await page.getByText(ARTIFACT_PATH).click();

    await expect
      .poll(async () =>
        page.evaluate(
          () =>
            (window as unknown as { __transitions: string[] }).__transitions,
        ),
      )
      .toContain("flex-grow");

    const artifactsPanel = page.locator("#artifacts");
    const handle = page.locator('[data-slot="resizable-handle"]');
    await expect(artifactsPanel).toBeVisible();
    await handle.hover();

    const transitionDuringDrag = await (async () => {
      const box = await handle.boundingBox();
      const mouse = page.mouse;
      await mouse.down();
      await mouse.move(box!.x - 120, box!.y + box!.height / 2, { steps: 5 });
      const transition = await page.evaluate(() => {
        // `[data-panel]` is the element the library sizes; the child that
        // `className` lands on is not the flex item.
        const panel = document
          .querySelector("#artifacts")
          ?.closest("[data-panel]");
        return panel
          ? window.getComputedStyle(panel).transitionProperty
          : "missing";
      });
      await mouse.up();
      return transition;
    })();

    expect(transitionDuringDrag).not.toContain("flex-grow");
  });
});
