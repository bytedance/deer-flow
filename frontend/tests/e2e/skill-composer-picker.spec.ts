import { expect, test, type Route } from "@playwright/test";

import { handleRunStream, mockLangGraphAPI } from "./utils/mock-api";

// #4062 MVP: the composer-owned skill picker. Desktop and mobile widths both
// must be able to open the picker, search, select, and send — the selected
// skill rides the message as the `/name ` prefix through the existing slash
// activation contract.
test.describe("Composer skill picker", () => {
  for (const viewport of [
    { width: 1280, height: 800, label: "desktop" },
    { width: 390, height: 844, label: "mobile" },
  ]) {
    test(`open, search, select, and send a skill (${viewport.label})`, async ({
      page,
    }) => {
      await page.setViewportSize({
        width: viewport.width,
        height: viewport.height,
      });

      let sentInput: unknown;
      const captureStream = async (route: Route) => {
        const body = route.request().postDataJSON() as { input?: unknown };
        sentInput = body?.input;
        return handleRunStream(route, {}, undefined, {
          responseMessage: {
            type: "ai",
            id: "skill-picker-ai-1",
            content: "Skill activated",
          },
          messageMetadata: {
            langgraph_node: "agent",
            langgraph_step: 1,
          },
        });
      };
      mockLangGraphAPI(page, {
        // Empty history so the streamed response is the visible content —
        // the default mock exchange would otherwise sit on top of it.
        createdThreadMessages: [],
        runStreamHandler: captureStream,
      });

      await page.goto("/workspace/chats/new");
      const textarea = page.getByPlaceholder(/how can i assist you/i);
      await expect(textarea).toBeVisible({ timeout: 15_000 });

      // Draft preservation: text typed before opening the picker must survive
      // selection — the chip-mode inline editor is seeded from it, matching
      // the reload-restore behavior for {text, skillName} drafts.
      const draft = "run the quarterly report";
      await textarea.fill(draft);

      await page.getByRole("button", { name: "Skills" }).click();
      const search = page.getByPlaceholder(/search skills/i);
      await expect(search).toBeVisible();
      // Search narrows the list; picking the item closes the picker and
      // installs the active-skill chip owned by the composer.
      await search.fill("data");
      await page.getByRole("option", { name: /data-analysis/ }).click();
      await expect(search).toBeHidden();
      await expect(
        page.getByRole("button", { name: "Remove /data-analysis" }),
      ).toBeVisible();

      // With a skill selected the composer swaps the plain textarea for the
      // chip + inline editor, so address it by its accessible name. The draft
      // typed above must already be inside it.
      const composer = page.getByRole("textbox", {
        name: /how can i assist you/i,
      });
      await expect(composer).toHaveText(draft);

      // Re-picking with a skill already active must swap the chip and keep
      // the draft — the same capture-and-reseed path runs from chip mode.
      await page.getByRole("button", { name: "Skills" }).click();
      await expect(search).toBeVisible();
      await search.fill("frontend");
      await page.getByRole("option", { name: /frontend-design/ }).click();
      await expect(search).toBeHidden();
      await expect(
        page.getByRole("button", { name: "Remove /frontend-design" }),
      ).toBeVisible();
      await expect(composer).toHaveText(draft);

      await composer.press("End");
      await composer.press("Enter");

      await expect.poll(() => sentInput).toBeTruthy();
      const messages = (
        sentInput as { messages?: Array<Record<string, unknown>> }
      )?.messages;
      const humanContent = (messages ?? []).find(
        (message) => message.type === "human",
      )?.content;
      const text =
        typeof humanContent === "string"
          ? humanContent
          : Array.isArray(humanContent)
            ? humanContent
                .map((block) =>
                  block && typeof block === "object" && "text" in block
                    ? String(block.text)
                    : "",
                )
                .join("")
            : "";
      expect(text.startsWith("/frontend-design ")).toBe(true);
      expect(text).toContain(draft);
      // The picker's contract ends at the wire: selection rode the message as
      // the /name prefix through the existing slash activation path (asserted
      // above). Response rendering from there is the general streaming
      // pipeline, covered by chat.spec.
    });
  }
});
