import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { readFile } from "node:fs/promises";
import { createServer } from "node:net";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

// Real Python plugin + host ACL/artifact routes + SQLite; deterministic saved
// states and synthetic identities. No model, production data or live login.
let gateway: ChildProcess;
let gatewayURL: string;
const backend = path.resolve(process.cwd(), "../backend");
const python =
  process.env.PLAYWRIGHT_PYTHON ?? path.join(backend, ".venv/bin/python");
const gatewayFixture = path.resolve(
  backend,
  "../examples/deerflow-extension-trajectory/tests/trajectory_plugin_gateway.py",
);
const viewer = `/workspace/extensions/community.trajectory/viewer?thread_id=${MOCK_THREAD_ID}`;
test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  const probe = createServer();
  await new Promise<void>((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const address = probe.address();
  if (!address || typeof address === "string") throw new Error("Missing port");
  await new Promise<void>((resolve) => probe.close(() => resolve()));
  gatewayURL = `http://127.0.0.1:${address.port}`;
  gateway = spawn(python, [gatewayFixture, String(address.port)], {
    cwd: backend,
    env: {
      ...process.env,
      PYTHONPATH: [backend, process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
    stdio: "pipe",
  });
  let diagnostics = "";
  gateway.stderr?.on("data", (chunk) => {
    diagnostics += String(chunk);
  });
  await expect
    .poll(
      async () => {
        if (gateway.exitCode !== null) throw new Error(diagnostics);
        return request
          .get(`${gatewayURL}/api/plugins`, {
            headers: { "x-test-user": "alice" },
          })
          .then((r) => r.status())
          .catch(() => 0);
      },
      { timeout: 60_000 },
    )
    .toBe(200);
});

test.afterAll(async () => {
  if (gateway?.exitCode === null) {
    const exited = new Promise<void>((resolve) =>
      gateway.once("exit", () => resolve()),
    );
    gateway.kill("SIGTERM");
    await exited;
  }
});

async function connect(page: Page, threadId = MOCK_THREAD_ID) {
  const identity = { user: "alice" };
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: threadId,
        title: "Trajectory integration",
        messages: [
          { id: "u", type: "human", content: "Inspect the saved trajectory" },
          { id: "a", type: "ai", content: "Ready" },
        ],
      },
    ],
  });
  const origin = new URL(
    process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
  ).origin;
  await page.route(
    /\/api\/(plugins|ext-trajectory|threads\/[^/]+\/artifacts)(\/|\?|$)/,
    async (route) => {
      const url = new URL(route.request().url());
      const cors = {
        "access-control-allow-origin": origin,
        "access-control-allow-credentials": "true",
        "access-control-allow-methods": "GET, OPTIONS",
        "access-control-allow-headers":
          "content-type, x-deerflow-plugin-viewer, x-csrf-token",
      };
      if (route.request().method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: cors });
        return;
      }
      const response = await route.fetch({
        url:
          gatewayURL +
          url.pathname.slice(url.pathname.indexOf("/api/")) +
          url.search,
        headers: { ...route.request().headers(), "x-test-user": identity.user },
      });
      await route.fulfill({
        response,
        headers: { ...response.headers(), ...cors },
      });
    },
  );
  return identity;
}

test("conversation menu, turn paging, image preview and full JSON/Markdown ZIP downloads", async ({
  page,
}, testInfo) => {
  test.setTimeout(90_000);
  await connect(page);
  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await page.getByRole("button", { name: "Trajectory", exact: true }).click();
  await page
    .getByRole("menuitem", {
      name: "View this conversation's trajectory",
      exact: true,
    })
    .click();
  await expect(page).toHaveURL(new RegExp(`thread_id=${MOCK_THREAD_ID}$`));
  await expect(
    page.getByRole("heading", { name: "运行轨迹", exact: true }),
  ).toBeVisible();
  const previews = page.locator(
    ".trajectory-row > details > summary .trajectory-preview",
  );
  await expect(previews).toHaveCount(2);
  await expect(previews.first()).toContainText("LATEST-TURN");
  await expect(page.locator(".trajectory-turn")).toHaveCount(1);

  const imageRow = page
    .locator(".trajectory-user")
    .filter({ hasText: "LATEST-TURN" });
  await imageRow.locator(":scope > details > summary").click();
  const thumbnail = imageRow.locator(".trajectory-image-card img");
  await expect
    .poll(() =>
      thumbnail.evaluate((node) => {
        const image = node as HTMLImageElement;
        return image.complete && image.naturalWidth > 0;
      }),
    )
    .toBe(true);
  await imageRow.getByRole("button", { name: /点击放大/ }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").locator("img")).toHaveAttribute(
    "src",
    /^blob:/,
  );
  await page.getByRole("button", { name: "关闭预览" }).click();

  // Export while only the latest turn is visible: download must still include
  // early, pre-compaction tool input/output, without the display's 4000 limit.
  await page.locator(".trajectory-export > summary").click();
  const jsonDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "JSON", exact: true }).click();
  const jsonFile = testInfo.outputPath("trajectory.json");
  await (await jsonDownload).saveAs(jsonFile);
  const data = JSON.parse(await readFile(jsonFile, "utf8")) as {
    history_complete: boolean;
    rows: { kind: string; text: string; tool_calls?: { name: string }[] }[];
  };
  expect(data.history_complete).toBe(true);
  expect(data.rows.map((row) => row.kind)).toEqual([
    "user",
    "assistant",
    "tool",
    "assistant",
    "compaction",
    "user",
    "assistant",
  ]);
  expect(data.rows[0]?.text).toContain("FIRST-TURN");
  expect(data.rows[1]?.tool_calls?.[0]?.name).toBe("read_file");
  expect(data.rows[2]?.text.length).toBeGreaterThan(4000);
  expect(data.rows[2]?.text).toContain("TOOL-RESULT-END");
  await expect(page.locator(".trajectory-turn")).toHaveCount(1);
  await page.locator(".trajectory-export > summary").click();
  const zipDownload = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Markdown＋图片 ZIP", exact: true })
    .click();
  const zipFile = testInfo.outputPath("trajectory.zip");
  await (await zipDownload).saveAs(zipFile);
  execFileSync(python, [
    "-c",
    [
      "import sys,zipfile,re",
      "with zipfile.ZipFile(sys.argv[1]) as z:",
      "    text=z.read('trajectory.md').decode()",
      "    assert 'FIRST-TURN' in text and 'LATEST-TURN' in text and 'TOOL-RESULT-END' in text",
      "    images=[n for n in z.namelist() if n.startswith('images/')]",
      "    assert len(images)==1 and images[0] in text",
      "    assert z.read(images[0]).startswith(b'\\x89PNG\\r\\n\\x1a\\n')",
    ].join("\n"),
    zipFile,
  ]);

  const earlier = page.waitForRequest((request) =>
    request.url().includes("/checkpoints?cursor="),
  );
  await page.getByRole("button", { name: "加载更早记录" }).click();
  await earlier;
  await expect(page.locator(".trajectory-turn")).toHaveCount(2);
  await expect(previews.first()).toContainText("FIRST-TURN");
  await expect(previews.last()).toContainText("LATEST-ANSWER");
  await page.getByRole("button", { name: "最新一轮", exact: true }).click();
  await expect(previews).toHaveCount(2);
  await expect(previews.first()).toContainText("LATEST-TURN");
  await page.getByRole("button", { name: "读取整个对话" }).click();
  await expect(page.locator(".trajectory-turn")).toHaveCount(2);
  await page.locator(".trajectory-turn-title").first().click();
  await expect(previews.first()).toBeHidden();
  await expect(previews.last()).toBeVisible();
});

test("switching account clears the visible trajectory and rejects old image/export URLs", async ({
  page,
  request,
}) => {
  const identity = await connect(page);
  await page.goto(viewer);
  await expect(page.locator(".trajectory-preview").first()).toContainText(
    "LATEST-TURN",
  );
  identity.user = "bob";
  const denied = page.waitForResponse(
    (response) =>
      response.url().includes("/checkpoints") && response.status() === 404,
  );
  await page.reload();
  await denied;
  await expect(page.getByText(/读取失败/)).toBeVisible();
  await expect(page.locator(".trajectory-row")).toHaveCount(0);
  await expect(page.locator(".trajectory-image-card")).toHaveCount(0);
  for (const suffix of [
    `/api/ext-trajectory/threads/${MOCK_THREAD_ID}/export?format=json`,
    `/api/ext-trajectory/threads/${MOCK_THREAD_ID}/export?format=markdown`,
    `/api/threads/${MOCK_THREAD_ID}/artifacts/mnt/user-data/uploads/image_1.png`,
  ]) {
    expect(
      (
        await request.get(gatewayURL + suffix, {
          headers: { "x-test-user": "bob" },
        })
      ).status(),
    ).toBe(404);
  }
});

test("compaction expands into full before/after columns with lazy loading", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await connect(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const comparisons: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/compaction?")) comparisons.push(request.url());
  });
  await page.goto(viewer);
  await expect(page.locator(".trajectory-preview").first()).toContainText(
    "LATEST-TURN",
  );
  await page.getByRole("button", { name: "读取整个对话" }).click();
  const compact = page.locator(".trajectory-compaction");
  await expect(compact).toHaveCount(1);
  expect(comparisons).toHaveLength(0);
  await compact.locator(":scope > details > summary").click();
  const before = compact.getByRole("region", { name: "压缩前", exact: true });
  const after = compact.getByRole("region", { name: "压缩后", exact: true });
  await expect(before).toContainText("FIRST-TURN");
  await expect(before).toContainText("read_file");
  await expect(before).toContainText("TOOL-RESULT-END");
  await expect(after).toContainText("COMPACTED: first turn researched");
  expect(comparisons).toHaveLength(1);
  const left = await before.boundingBox();
  const right = await after.boundingBox();
  expect(left && right && left.x + left.width <= right.x).toBeTruthy();
  await after
    .getByText("查看压缩后保留的消息（1 条）", { exact: true })
    .click();
  await expect(
    after.getByText("FIRST-ANSWER: source inspected", { exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 600, height: 900 });
  const mobileBefore = await before.boundingBox();
  const mobileAfter = await after.boundingBox();
  expect(
    mobileBefore &&
      mobileAfter &&
      mobileAfter.y >= mobileBefore.y + mobileBefore.height,
  ).toBeTruthy();
});

test("native child steps appear as outer rows beside their delegation and export full evidence", async ({
  page,
}, testInfo) => {
  test.setTimeout(90_000);
  const threadId = "00000000-0000-0000-0000-000000000003";
  await connect(page, threadId);
  await page.goto(
    `/workspace/extensions/community.trajectory/viewer?thread_id=${threadId}`,
  );
  const parent = page
    .locator(
      ".trajectory-turn-rows > .trajectory-assistant:not(.trajectory-subagent-row)",
    )
    .filter({ hasText: "Delegate two children" });
  await expect(parent).toHaveCount(1);
  const childRows = page.locator(
    ".trajectory-turn-rows > .trajectory-subagent-row",
  );
  await expect(childRows).toHaveCount(8);
  expect(
    await parent
      .locator(":scope > details")
      .evaluate((box) => (box as HTMLDetailsElement).open),
  ).toBe(false);
  await expect(parent.locator(".trajectory-subagent-row")).toHaveCount(0);
  await expect(page.locator(".trajectory-subagents")).toHaveCount(0);
  const first = childRows.and(
    page.locator('[data-execution-id^="parent-two-outer-shared-"]'),
  );
  const second = childRows.and(
    page.locator('[data-execution-id^="parent-two-outer-second-"]'),
  );
  await expect(first).toHaveCount(4);
  await expect(second).toHaveCount(4);
  const tool = first.and(page.locator(".trajectory-tool"));
  await expect(tool.locator(".trajectory-line")).toContainText(
    "子 agent · bash · 工具结果",
  );
  await expect(tool.locator(".trajectory-preview")).toContainText("echo_child");
  await tool.locator(":scope > details > summary").click();
  await expect(
    tool.locator("pre").filter({ hasText: "CHILD-TOOL-BEGIN" }),
  ).toContainText("CHILD-TOOL-BEGIN");
  await expect(
    page.getByText(
      /子执行：|所属委派|执行内保存顺序|证据定位|调用 ID：|调用与结果|完全相同调用/,
    ),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /^定位调用$|^定位结果$/ }),
  ).toHaveCount(0);
  const order = await page.locator(".trajectory-turn-rows").evaluate((list) => {
    const rows = Array.from(list.children);
    const start = rows.findIndex(
      (row) =>
        !row.classList.contains("trajectory-subagent-row") &&
        row.textContent?.includes("Delegate two children"),
    );
    const end = rows.findIndex(
      (row, index) =>
        index > start &&
        row.classList.contains("trajectory-tool") &&
        !row.classList.contains("trajectory-subagent-row"),
    );
    return (
      start >= 0 &&
      end > start &&
      rows
        .slice(start + 1, end)
        .filter((row) => row.classList.contains("trajectory-subagent-row"))
        .length === 8
    );
  });
  expect(order).toBe(true);
  await page.locator(".trajectory-export > summary").click();
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "JSON", exact: true }).click();
  const file = testInfo.outputPath("parent-and-children.json");
  await (await pending).saveAs(file);
  const data = JSON.parse(await readFile(file, "utf8"));
  const children = data.rows.flatMap(
    (row: { tool_calls?: { subagents?: unknown[] }[] }) =>
      (row.tool_calls ?? []).flatMap((call) => call.subagents ?? []),
  );
  expect(children).toHaveLength(4);
  expect(JSON.stringify(children)).toContain("CHILD-TOOL-END");
});

test("measured durations locate slow operations separately from failures and retain legacy unknowns", async ({
  page,
}, testInfo) => {
  test.setTimeout(90_000);
  const threadId = "00000000-0000-0000-0000-000000000004";
  await page.addInitScript(() => {
    const key = "deerflow.trajectory.slowThresholdsMs";
    if (localStorage.getItem(key) === null) {
      localStorage.setItem(key, JSON.stringify({ "tool:timed_echo": 60_000 }));
    }
  });
  await connect(page, threadId);
  await page.goto(
    `/workspace/extensions/community.trajectory/viewer?thread_id=${threadId}`,
  );
  await page.getByRole("button", { name: "读取整个对话", exact: true }).click();
  const panel = page.locator(".trajectory-timing-panel");
  await expect(panel.locator(":scope > summary")).toContainText(
    "5 项已记录 / 1 项未记录",
  );
  const legacy = page
    .locator(".trajectory-row")
    .filter({ hasText: "LEGACY-ANSWER" });
  await expect(legacy.locator(".trajectory-duration")).toHaveText("未记录");
  await panel.locator(":scope > summary").click();
  const filter = page.getByRole("combobox", { name: "耗时定位范围" });
  await filter.selectOption("slow");
  await expect(panel.locator(".trajectory-timing-list button")).toHaveCount(1);
  await expect(panel.locator(".trajectory-timing-list button")).toContainText(
    "timed_echo",
  );
  await expect(panel.locator(".trajectory-timing-list button")).toContainText(
    "完成",
  );
  await panel.locator(".trajectory-timing-list button").click();
  const located = page.locator(".trajectory-located");
  await expect(located).toContainText("TIMED-TOOL-RESULT");
  await expect(located.locator(".trajectory-timing-note")).toHaveText(
    /20\d{2}.*工具调用耗时/,
  );
  expect(
    await located
      .locator(":scope > details")
      .evaluate((box) => (box as HTMLDetailsElement).open),
  ).toBe(true);
  await filter.selectOption("failed");
  await expect(panel.locator(".trajectory-timing-list button")).toHaveCount(2);
  await expect(page.locator(".trajectory-anomaly")).toHaveCount(2);
  await expect(page.locator(".trajectory-slow")).toHaveCount(1);
  await expect(page.locator(".trajectory-row.trajectory-timing")).toHaveCount(
    1,
  );
  await expect(page.locator(".trajectory-row.trajectory-timing")).toContainText(
    "超时",
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await panel.getByText("设置慢阈值", { exact: true }).click();
  await expect(panel.getByRole("spinbutton")).toHaveCount(2);
  const toolDefault = panel.getByRole("spinbutton", { name: "工具（s）" });
  const modelDefault = panel.getByRole("spinbutton", { name: "模型（s）" });
  await expect(toolDefault).toHaveAttribute("placeholder", "0.01");
  await expect(modelDefault).toHaveAttribute("placeholder", "1");
  const saveThresholds = panel.getByRole("button", { name: "保存慢阈值" });
  await toolDefault.fill("1");
  await saveThresholds.click();
  await filter.selectOption("slow");
  await expect(panel.locator(".trajectory-timing-list button")).toHaveCount(0);
  await modelDefault.fill("0.001");
  await saveThresholds.click();
  await expect(panel.locator(".trajectory-timing-list button")).toHaveCount(3);
  await expect(
    panel.locator(".trajectory-timing-list button").filter({ hasText: "超时" }),
  ).toContainText(/模型完整响应.*慢.*超时/);

  await page.reload();
  await page.getByRole("button", { name: "读取整个对话", exact: true }).click();
  await expect(panel.locator(":scope > summary")).toContainText("5 项已记录");
  await panel.locator(":scope > summary").click();
  await filter.selectOption("slow");
  await expect(panel.locator(".trajectory-timing-list button")).toHaveCount(3);
  await page.locator(".trajectory-export > summary").click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "JSON", exact: true }).click();
  const file = testInfo.outputPath("thresholds.json");
  await (await download).saveAs(file);
  const data = JSON.parse(await readFile(file, "utf8")) as {
    rows: { timing?: { operation: string; is_slow: boolean } }[];
  };
  expect(
    data.rows
      .filter((row) => row.timing?.is_slow)
      .map((row) => row.timing?.operation),
  ).toEqual(["model", "model", "model"]);

  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
});

test("tool failures and retry clues have a dedicated locator with confidence labels", async ({
  page,
}) => {
  const threadId = "00000000-0000-0000-0000-000000000006";
  await connect(page, threadId);
  await page.goto(
    `/workspace/extensions/community.trajectory/viewer?thread_id=${threadId}`,
  );
  const shell = page
    .locator(".trajectory-tool")
    .filter({ hasText: "EXIT_CODE=1" });
  await shell.locator(":scope > details > summary").click();
  await expect(shell.locator(".trajectory-body pre")).toContainText(
    "EXIT_CODE=1",
  );
  await expect(shell).toContainText("进程返回码：未记录");
  await expect(shell.locator(".trajectory-anomaly")).toHaveCount(0);

  const panel = page.locator(".trajectory-tools-panel");
  await expect(panel.locator(".trajectory-panel-stats")).toHaveText(
    "2 项失败 · 1 项待核对 · 3 项重试线索",
  );
  await panel.locator(":scope > summary").click();
  const timingPanel = page.locator(".trajectory-timing-panel");
  await timingPanel.locator(":scope > summary").click();
  await expect
    .poll(async () => {
      const tools = await panel.boundingBox();
      const timing = await timingPanel.boundingBox();
      if (tools && timing) return Math.abs(tools.height - timing.height);
    })
    .toBeLessThanOrEqual(1);
  const filter = page.getByRole("combobox", { name: "工具失败与重试范围" });
  const results = panel.locator(".trajectory-tools-list");
  await expect(results.getByRole("button")).toHaveCount(6);
  await expect
    .poll(() =>
      results.evaluate((list) => {
        const { top, bottom } = list.getBoundingClientRect();
        return Array.from(list.querySelectorAll("button")).filter((button) => {
          const rect = button.getBoundingClientRect();
          return rect.top >= top - 1 && rect.bottom <= bottom + 1;
        }).length;
      }),
    )
    .toBe(6);
  await filter.selectOption("failure");
  await expect(results.getByRole("button")).toHaveCount(3);
  await expect.poll(() => results.evaluate((list) => list.scrollTop)).toBe(0);
  await panel
    .getByRole("button", { name: /read_file · 失败 ·/ })
    .first()
    .click();
  await expect(page.locator(".trajectory-located")).toContainText(
    "FileNotFoundError",
  );
  // Locator reopens a collapsed user turn and selects the invocation, not a
  // summary that merely says it retried.
  await page.locator(".trajectory-turn-title").click();
  await filter.selectOption("repeat");
  await expect(panel.locator(".trajectory-tools-list button")).toHaveCount(1);
  await panel.locator(".trajectory-tools-list button").click();
  await expect(page.locator(".trajectory-located")).toContainText(
    "调用工具 · read_file",
  );
  await expect(page.locator(".trajectory-turn > details")).toHaveAttribute(
    "open",
    "",
  );
  await filter.selectOption("possible");
  await expect(panel.locator(".trajectory-tools-list button")).toHaveCount(2);
  await panel.getByRole("button", { name: /glob · 可能重试/ }).click();
  await expect(page.locator(".trajectory-located")).toContainText(
    "调用工具 · glob",
  );
});
