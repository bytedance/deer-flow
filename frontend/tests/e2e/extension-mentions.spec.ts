import { createHash } from "node:crypto";

import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("plugin candidates coexist with skills, survive draft reload and submit structured references", async ({
  page,
  baseURL,
}, testInfo) => {
  mockLangGraphAPI(page, {
    skills: [
      { name: "research", description: "Research a topic", enabled: true },
    ],
  });
  const source = `export default { apiVersion: 1, module: 'team', mentionProviders: [
    { id: 'people', label: 'Team members', search: async (query, ctx) => {
      const items = await ctx.callBackend('search', { query, threadId: ctx.threadId });
      return items;
    } },
    { id: 'broken', label: 'Unavailable', search: async () => { throw Error('offline'); } }
  ] };`;
  const entry = `/api/plugins/modules/team/${createHash("sha256").update(source).digest("hex")}.mjs`;
  let enabled = true;
  const searches: unknown[] = [];
  await page.route("**/api/plugins**", async (route) => {
    const url = new URL(route.request().url());
    const headers = {
      "access-control-allow-origin": new URL(baseURL!).origin,
      "access-control-allow-credentials": "true",
    };
    if (url.pathname.endsWith("/api/plugins"))
      return route.fulfill({
        headers,
        json: [
          {
            namespace: "community.team",
            viewer_id: "default",
            module: "team",
            entry,
            title: "Team",
            description: "",
            settings: { enabled },
            backend_actions: ["search"],
          },
        ],
      });
    if (url.pathname.endsWith(entry))
      return route.fulfill({
        headers,
        contentType: "text/javascript",
        body: source,
      });
    if (url.pathname.endsWith("/actions/search")) {
      searches.push(route.request().postDataJSON());
      expect(route.request().headers()["x-deerflow-plugin-viewer"]).toBe(
        "default",
      );
      return route.fulfill({
        headers,
        json: [{ id: "alice", label: "Alice" }],
      });
    }
    return route.fulfill({ status: 404, headers });
  });
  await page.goto("/workspace/chats/new");
  const input = page.getByRole("textbox", { name: /how can i assist you/i });
  await input.fill("Ask @");
  await expect(
    page.getByRole("option", { name: "research Research a topic" }),
  ).toBeVisible();
  await expect(
    page.getByRole("option", { name: "Alice Team members" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("extension-mentions.png"),
  });
  await page.getByRole("option", { name: "Alice Team members" }).click();
  await expect(page.getByTestId("extension-mention-chip")).toContainText(
    "Alice",
  );
  await expect.poll(() => searches.length).toBeGreaterThan(0);
  await page.reload();
  await expect(page.getByTestId("extension-mention-chip")).toContainText(
    "Alice",
  );
  const request = page.waitForRequest(
    (r) => r.method() === "POST" && r.url().includes("/runs/stream"),
  );
  await input.press("Enter");
  const message = (await request).postDataJSON().input.messages.at(-1);
  expect(message.content).toEqual([{ type: "text", text: "Ask @Alice" }]);
  expect(message.additional_kwargs.extension_mentions).toEqual([
    {
      namespace: "community.team",
      provider: "people",
      id: "alice",
      label: "Alice",
    },
  ]);
  enabled = false;
  await page.goto("/workspace/chats/new");
  await page.reload();
  await input.fill("@");
  await expect(
    page.getByRole("option", { name: "research Research a topic" }),
  ).toBeVisible();
  await expect(
    page.getByRole("option", { name: "Alice Team members" }),
  ).toHaveCount(0);
});
