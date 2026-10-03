// Run after starting the documented loopback fixture. This is a browser regression suite.
import assert from "node:assert/strict";
import {
  chromium,
  expect,
} from "../../frontend/node_modules/@playwright/test/index.mjs";
const base = process.env.TEAM_PREVIEW_URL ?? "http://team-preview.test:8197";
const apiBase = new URL(base);
apiBase.hostname = "127.0.0.1";
const browser = await chromium.launch({
  headless: true,
  args: [
    "--host-resolver-rules=MAP team-preview.test 127.0.0.1",
    "--no-proxy-server",
  ],
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1050 },
    extraHTTPHeaders: { "x-test-user": `browser-${Date.now()}` },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let requests = 0,
    unchanged = 0;
  page.on("request", (r) => {
    if (r.url().includes("/actions/get")) requests++;
  });
  page.on("response", async (r) => {
    if (r.url().includes("/actions/get")) {
      try {
        if ((await r.json()).unchanged) unchanged++;
      } catch {}
    }
  });
  await page.route(
    "**/api/agents",
    async (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: '{"detail":"fixture outage"}',
      }),
    { times: 1 },
  );
  await page.goto(base);
  assert.equal(await page.evaluate(() => isSecureContext), false);
  assert.equal(
    await page.evaluate(() => typeof crypto.randomUUID),
    "undefined",
  );
  await expect(page.getByText(/Cannot load agents/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create team", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Reload agents", exact: true })
    .click();
  await page
    .getByLabel("Search agents", { exact: true })
    .fill("source evidence");
  await page.getByRole("checkbox", { name: "Research", exact: true }).check();
  await expect(
    page.getByRole("checkbox", { name: "Review", exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("Search agents", { exact: true }).fill("quality");
  await page.getByRole("checkbox", { name: "Review", exact: true }).check();
  await page.getByLabel("Search agents", { exact: true }).clear();
  await expect(
    page.getByRole("button", { name: "Create team", exact: true }),
  ).toBeEnabled();
  await page.getByLabel("Team name", { exact: true }).fill("Release readiness");
  await page
    .getByLabel("Shared goal", { exact: true })
    .fill(
      "Research the evidence, review the findings, and prepare a release recommendation.",
    );
  if (process.env.TEAM_SCREENSHOT)
    await page.screenshot({
      path: process.env.TEAM_SCREENSHOT.replace(".png", "-create.png"),
      fullPage: true,
    });
  await page.getByRole("button", { name: "Create team", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Release readiness", exact: true }),
  ).toBeVisible();
  const candidates = await page.evaluate(() =>
    window.teamPlugin.mentionProviders[0].search(
      "Research",
      window.teamContext,
    ),
  );
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].description, "researcher");
  const composer = page.getByLabel("Message to team", { exact: true });
  await composer.fill("@Res");
  await expect(page.getByRole("option", { name: /@Research/ })).toBeVisible();
  await composer.press("Enter");
  await expect(
    page.getByRole("button", {
      name: "Remove recipient Research",
      exact: true,
    }),
  ).toBeVisible();
  await composer.fill("Check the synthetic release evidence.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await composer.fill("Keep this unfinished draft while the result arrives.");
  await expect(
    page.getByText("Release evidence verified. See the shared team record.", {
      exact: true,
    }),
  ).toBeVisible({ timeout: 12000 });
  await expect(composer).toHaveValue(
    "Keep this unfinished draft while the result arrives.",
  );
  await expect(page.locator(".task-message").first()).toContainText(
    "You → @Research",
  );
  await expect(page.locator(".task-message").first()).toContainText(
    "Check the synthetic release evidence.",
  );
  // A peer request uses the real backend handler and completion loop.
  const team = await page.evaluate(() =>
    window.teamContext.callBackend("list", {}).then((r) => r.teams[0]),
  );
  const [research, review] = team.members;
  await page.request
    .post(`${apiBase.origin}/preview/peer-request`, {
      data: {
        team_id: team.id,
        source_thread: research.thread_id,
        member_id: review.id,
        text: "Review the researcher's source evidence.",
      },
    })
    .then(async (r) => assert.equal(r.status(), 200));
  await expect(
    page.getByText("Research → @Review", { exact: true }),
  ).toBeVisible({ timeout: 12000 });
  await expect(
    page.getByText("Returned to Research", { exact: true }),
  ).toBeVisible({ timeout: 12000 });
  await expect(composer).toHaveValue(
    "Keep this unfinished draft while the result arrives.",
  );
  // No-change polling must keep the existing message DOM and open details.
  const details = page
    .locator(".task-message")
    .first()
    .locator(".task-details");
  await details.locator("summary").click();
  const requestCount = requests;
  await expect
    .poll(() => requests, { timeout: 6000 })
    .toBeGreaterThan(requestCount);
  await expect(details).toHaveAttribute("open", "");
  await expect.poll(() => unchanged, { timeout: 6000 }).toBeGreaterThan(0);
  await page
    .getByRole("button", { name: "Open Research conversation", exact: true })
    .click();
  assert.equal(
    await page.evaluate(() => window.openedThread),
    research.thread_id,
  );
  const foreign = await page.request.post(
    `${apiBase.origin}/api/plugins/community.agent-teams/actions/list`,
    { headers: { "x-test-user": "bob" }, data: {} },
  );
  assert.deepEqual((await foreign.json()).teams, []);
  await composer.fill("");
  if (process.env.TEAM_SCREENSHOT)
    await page.screenshot({
      path: process.env.TEAM_SCREENSHOT,
      fullPage: true,
    });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  if (process.env.TEAM_SCREENSHOT)
    await page.screenshot({
      path: process.env.TEAM_SCREENSHOT.replace(".png", "-mobile.png"),
      fullPage: true,
    });
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.waitForTimeout(200);
  if (process.env.TEAM_SCREENSHOT)
    await page.screenshot({
      path: process.env.TEAM_SCREENSHOT.replace(".png", "-dark.png"),
      fullPage: true,
    });
  // Theme tokens must keep the small delete action readable in both themes.
  await page.getByText("Manage", { exact: true }).click();
  for (const dark of [false, true]) {
    await page.evaluate(
      (dark) => document.documentElement.classList.toggle("dark", dark),
      dark,
    );
    const contrast = await page
      .getByRole("button", { name: "Delete finished team", exact: true })
      .evaluate((button) => {
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 1;
        const ctx = canvas.getContext("2d");
        function luminance(color) {
          ctx.clearRect(0, 0, 1, 1);
          ctx.fillStyle = color;
          ctx.fillRect(0, 0, 1, 1);
          return [...ctx.getImageData(0, 0, 1, 1).data]
            .slice(0, 3)
            .map((v) => v / 255)
            .map((v) =>
              v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4,
            )
            .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
        }
        const foreground = luminance(getComputedStyle(button).color);
        const background = luminance(
          getComputedStyle(button.parentElement).backgroundColor,
        );
        return (
          (Math.max(foreground, background) + 0.05) /
          (Math.min(foreground, background) + 0.05)
        );
      });
    assert.ok(
      contrast >= 4.5,
      `Delete contrast in ${dark ? "dark" : "light"} theme: ${contrast}`,
    );
  }
  await page.getByText("Manage", { exact: true }).click();
  // Multiple recipients create one job each. Polling failures preserve the composer.
  await page
    .getByRole("button", { name: "Remove recipient Research", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Mention Research", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Mention Review", exact: true })
    .click();
  await composer.fill("Independently check the next release.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.locator(".task-message")).toHaveCount(4, {
    timeout: 12000,
  });
  await expect(page.locator(".task-message").nth(3)).toContainText(
    "Completed",
    { timeout: 12000 },
  );
  await page.route(
    "**/actions/get",
    async (route) => route.fulfill({ status: 503, body: "{}" }),
    { times: 1 },
  );
  await composer.fill("Keep this draft through a failed refresh.");
  await expect(
    page.getByText("Updates interrupted · retrying automatically", {
      exact: true,
    }),
  ).toBeVisible({ timeout: 6000 });
  await expect(page.getByText("● Live updates", { exact: true })).toBeVisible({
    timeout: 6000,
  });
  await expect(composer).toHaveValue(
    "Keep this draft through a failed refresh.",
  );
  // Opening an existing team should return to its conversation, not a blank form.
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Release readiness", exact: true }),
  ).toBeVisible();
  await page.getByText("Manage", { exact: true }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "Delete finished team", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Create team", exact: true }),
  ).toBeVisible();
  // Exercise the submitted names through real create validation, including
  // collisions with naturally suffixed titles and the UTF-8 byte ceiling.
  const nameCases = [
    ["X".repeat(80) + "A", "X".repeat(80) + "B", "X".repeat(76) + " (2)"],
    ["Research", "Research", "Research (2)"],
    ["Research ", "Research", " Research"],
    ["研".repeat(80), "研".repeat(79) + "究", "😀".repeat(50)],
  ];
  for (const [index, titles] of nameCases.entries()) {
    await page.route(
      "**/api/agents",
      (route) =>
        route.fulfill({
          json: {
            agents: titles.map((display_name, i) => ({
              name: ["researcher", "reviewer", "writer"][i],
              display_name,
              description: "Name boundary regression",
            })),
          },
        }),
      { times: 1 },
    );
    await page.getByRole("button", { name: "+ New team", exact: true }).click();
    await expect(page.getByRole("checkbox")).toHaveCount(3);
    for (const checkbox of await page.getByRole("checkbox").all())
      await checkbox.check();
    const title = `Name boundaries ${index}`;
    await page.getByLabel("Team name", { exact: true }).fill(title);
    await page
      .getByLabel("Shared goal", { exact: true })
      .fill("Check member names");
    const created = page.waitForResponse((r) =>
      r.url().endsWith("/actions/create"),
    );
    await page
      .getByRole("button", { name: "Create team", exact: true })
      .click();
    const response = await created;
    assert.equal(response.status(), 200, await response.text());
    const result = await response.json();
    const names = result.members.map((m) => m.name);
    assert.equal(new Set(names).size, 3);
    assert.ok(
      names.every(
        (name) =>
          name === name.trim() &&
          name.length <= 80 &&
          new TextEncoder().encode(name).length <= 160,
      ),
    );
    await expect(
      page.getByRole("heading", { name: title, exact: true }),
    ).toBeVisible();
    await page.getByText("Manage", { exact: true }).click();
    page.once("dialog", (dialog) => dialog.accept());
    await page
      .getByRole("button", { name: "Delete finished team", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Create team", exact: true }),
    ).toBeVisible();
  }
  await page.evaluate(() => window.teamView.dispose());
  assert.equal(await page.locator(".agent-teams").count(), 0);
  const finalCount = requests;
  await page.waitForTimeout(2300);
  assert.equal(requests, finalCount);
  assert.deepEqual(errors, []);
  console.log(
    "PASS: HTTP, catalog outage/retry/search/selection, @ picker, real task/result association, peer handoff/receipt, auto-refresh, stable drafts/details, conditional updates, isolation, mobile/dark, reopen, delete, disposal",
  );
} finally {
  await browser.close();
}
