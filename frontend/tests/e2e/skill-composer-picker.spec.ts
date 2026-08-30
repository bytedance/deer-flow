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
      // chip + inline editor, so address it by its accessible name.
      const composer = page.getByRole("textbox", {
        name: /how can i assist you/i,
      });
      await composer.fill("run the quarterly report");
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
      expect(text.startsWith("/data-analysis ")).toBe(true);
      // The picker's contract ends at the wire: selection rode the message as
      // the /name prefix through the existing slash activation path (asserted
      // above). Response rendering from there is the general streaming
      // pipeline, covered by chat.spec.
    });
  }
});
