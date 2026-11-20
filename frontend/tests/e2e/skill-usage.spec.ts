import { mkdir } from "node:fs/promises";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000009922";
const RUN_ID = "skill-usage-run";
const skills = [
  {
    name: "using-superpowers",
    description: "开始任务前识别适用的技能，并按技能工作流推进。",
    category: "custom",
    path: "/mnt/skills/custom/using-superpowers/SKILL.md",
    content:
      "---\nname: using-superpowers\ndescription: 开始任务前识别适用的技能，并按技能工作流推进。\n---\n# Using Superpowers\n\n在执行任务前，先检查是否有适用的技能。\n\n## 工作流程\n\n1. 理解用户请求，识别任务类型。\n2. 读取相关技能的说明与参考资料。\n3. 按工作流完成任务，持续验证结果。\n\n## 完成前验证\n\n以实际命令输出和检查结果为依据。记录遇到的问题与处理方式，再汇报最终结果。\n\n> 此处展示的是本轮加载时保存的技能内容。",
    content_hash: "a".repeat(64),
    activation: "slash",
    partial: false,
  },
  {
    name: "verification-before-completion",
    description: "交付前运行检查，并用实际结果验证完成情况。",
    category: "public",
    path: "/mnt/skills/public/verification-before-completion/SKILL.md",
    content:
      "# Verification Before Completion\n\n## 验证步骤\n\n- 运行相关测试与静态检查。\n- 检查实际界面与交互。\n- 将验证结果与交付内容一并提供。",
    content_hash: "b".repeat(64),
    activation: "automatic",
    partial: false,
  },
];

function messages(includeSkills = true) {
  return [
    {
      type: "human",
      id: "user",
      content: "帮我检查这次改动，完成后给我看看结果。",
      run_id: RUN_ID,
    },
    {
      type: "ai",
      id: "start",
      content: "我会先读取适用的技能，再检查改动和运行验证。",
      run_id: RUN_ID,
      additional_kwargs: includeSkills ? { skill_usage: skills[0] } : {},
    },
    {
      type: "ai",
      id: "read",
      content: "",
      run_id: RUN_ID,
      tool_calls: [
        {
          id: "read-call",
          name: "read_file",
          args: { path: skills[1]!.path, description: "读取完成前验证技能" },
        },
      ],
    },
    {
      type: "tool",
      id: "loaded",
      content: skills[1]!.content,
      name: "read_file",
      tool_call_id: "read-call",
      run_id: RUN_ID,
      additional_kwargs: includeSkills ? { skill_usage: skills[1] } : {},
    },
    {
      type: "ai",
      id: "final",
      content:
        "检查完成，本次改动已在本地验证。\n\n- **功能检查**：入口、列表和详情面板均可正常使用。\n- **历史记录**：刷新后仍能查看本轮使用的技能。\n- **界面适配**：桌面使用侧栏，手机使用抽屉。\n\n代码和验证结果已保留在本地。",
      run_id: RUN_ID,
    },
  ];
}

async function setup(page: Page, includeSkills = true) {
  await page.addInitScript(() => localStorage.setItem("theme", "dark"));
  await page
    .context()
    .addCookies([
      { name: "locale", value: "zh-CN", url: "http://localhost:3000" },
    ]);
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: "技能使用记录",
        messages: messages(includeSkills),
      },
    ],
  });
  await page.goto(`/workspace/chats/${THREAD_ID}`);
  await expect(page.getByText("检查完成，本次改动已在本地验证。")).toBeVisible({
    timeout: 60_000,
  });
}

async function screenshot(page: Page, name: string) {
  const directory = process.env.SKILL_USAGE_SCREENSHOT_DIR;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  await page.screenshot({
    path: join(directory, name),
    fullPage: true,
    animations: "disabled",
  });
  if (name.startsWith("skills-menu")) {
    const menu = await page.getByRole("menu").boundingBox();
    const trigger = await page
      .getByRole("button", { name: "使用的技能", exact: true })
      .boundingBox();
    if (menu && trigger) {
      const x = Math.max(0, Math.min(menu.x, trigger.x) - 12);
      const y = Math.max(0, menu.y - 12);
      await page.screenshot({
        path: join(directory, name.replace(".png", "-closeup.png")),
        animations: "disabled",
        clip: {
          x,
          y,
          width:
            Math.max(menu.x + menu.width, trigger.x + trigger.width) - x + 12,
          height: trigger.y + trigger.height - y + 12,
        },
      });
    }
  }
}

test("shows one skill menu per run, switches snapshots and restores after reload", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await setup(page);
  const trigger = page.getByRole("button", { name: "使用的技能", exact: true });
  await expect(trigger).toHaveCount(1);
  const toolbarSizes = await trigger
    .locator("..")
    .locator("button")
    .evaluateAll((buttons) =>
      buttons.map((button) => ({
        button: Math.round(button.getBoundingClientRect().width),
        icon: Math.round(
          button.querySelector("svg")!.getBoundingClientRect().width,
        ),
        color: getComputedStyle(button).color,
      })),
    );
  expect(toolbarSizes).toHaveLength(4);
  expect(
    toolbarSizes.every(({ button, icon }) => button === 32 && icon === 16),
  ).toBe(true);
  expect(new Set(toolbarSizes.map(({ color }) => color)).size).toBe(1);
  await trigger.hover();
  await expect(
    page.getByRole("menuitem", { name: /using-superpowers.*自定义/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("menuitem", {
      name: /verification-before-completion.*内置/,
    }),
  ).toBeVisible();
  await screenshot(page, "skills-menu.png");
  const skillName = page
    .getByRole("menuitem", { name: /using-superpowers/ })
    .getByText("using-superpowers");
  await skillName.hover();
  await expect(skillName).toHaveCSS("text-decoration-line", "underline");
  await screenshot(page, "skills-menu-name-hover.png");
  await page.getByRole("menuitem", { name: /using-superpowers/ }).click();
  const panel = page.getByRole("region", { name: "SKILL.md", exact: true });
  await expect(
    panel.getByRole("heading", { name: "Using Superpowers", exact: true }),
  ).toBeVisible();
  await expect(panel.getByText(skills[0]!.path)).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "复制技能快照" }),
  ).toBeVisible();
  await screenshot(page, "skills-detail-desktop.png");
  const handle = page.locator('[data-slot="resizable-handle"]').first();
  await handle.hover();
  const initialWidth = (await panel.boundingBox())!.width;
  await page.mouse.down();
  const bounds = (await handle.boundingBox())!;
  await page.mouse.move(bounds.x - 120, bounds.y + bounds.height / 2, {
    steps: 12,
  });
  await page.mouse.up();
  await expect
    .poll(async () => (await panel.boundingBox())!.width)
    .toBeGreaterThan(initialWidth + 50);
  await trigger.click();
  await page
    .getByRole("menuitem", { name: /verification-before-completion/ })
    .click();
  await expect(
    panel.getByRole("heading", { name: "Verification Before Completion" }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(panel).toBeHidden();
  await page.reload();
  await expect(trigger).toHaveCount(1);
  await trigger.click();
  await page.getByRole("menuitem", { name: /using-superpowers/ }).click();
  await expect(
    panel.getByRole("heading", { name: "Using Superpowers", exact: true }),
  ).toBeVisible();
});

test("mobile opens a readable detail sheet and supports closing", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);
  await page.getByRole("button", { name: "使用的技能", exact: true }).click();
  await page.getByRole("menuitem", { name: /using-superpowers/ }).click();
  const panel = page.getByRole("region", { name: "SKILL.md", exact: true });
  await expect(
    panel.getByRole("heading", { name: "Using Superpowers", exact: true }),
  ).toBeVisible();
  expect((await panel.boundingBox())!.width).toBeLessThan(391);
  await screenshot(page, "skills-detail-mobile.png");
  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
});

test("older history without load evidence does not invent skill usage", async ({
  page,
}) => {
  await setup(page, false);
  await expect(
    page.getByRole("button", { name: "使用的技能", exact: true }),
  ).toHaveCount(0);
});

test("details share the browser panel and can reopen after drag collapse", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await setup(page);
  const trigger = page.getByRole("button", { name: "使用的技能", exact: true });
  const openDetail = async () => {
    await trigger.click();
    await page.getByRole("menuitem", { name: /using-superpowers/ }).click();
    await expect(
      page.getByRole("region", { name: "SKILL.md", exact: true }),
    ).toBeVisible();
  };
  await openDetail();
  await page.getByTestId("browser-trigger").click();
  await expect(
    page.getByRole("region", { name: "SKILL.md", exact: true }),
  ).toBeHidden();
  await openDetail();
  await expect(page.getByTestId("browser-trigger")).not.toHaveAttribute(
    "aria-label",
    "关闭",
  );
  const handle = page.locator('[data-slot="resizable-handle"]').first();
  await handle.hover();
  const bounds = (await handle.boundingBox())!;
  await page.mouse.down();
  await page.mouse.move(1438, bounds.y + bounds.height / 2, { steps: 15 });
  await page.mouse.up();
  await expect(
    page.getByRole("region", { name: "SKILL.md", exact: true }),
  ).toBeHidden();
  await openDetail();
});

test("terminal-only history keeps original raw copy and scrolls long snapshots safely", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  const content = `---\nname: long-report\ndescription: Long report workflow\n---\n# Long report\n\n[Local template](templates/apa.md)\n\n![Local diagram](images/flow.png)\n\n${"Paragraph with instructions.\n\n".repeat(160)}## End of snapshot`;
  const original = { ...skills[0]!, content };
  await page
    .context()
    .addCookies([
      { name: "locale", value: "zh-CN", url: "http://localhost:3000" },
    ]);
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: "Archived skill history",
        messages: [
          {
            type: "ai",
            id: "final-only",
            content: "历史已恢复。",
            run_id: RUN_ID,
            additional_kwargs: { skill_usages: [original] },
          },
        ],
      },
    ],
  });
  await page.goto(`/workspace/chats/${THREAD_ID}`);
  await page.getByRole("button", { name: "使用的技能", exact: true }).click();
  await page.getByRole("menuitem", { name: /using-superpowers/ }).click();
  const panel = page.getByRole("region", { name: "SKILL.md", exact: true });
  await expect(
    panel.getByRole("heading", { name: "Long report", exact: true }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "复制技能快照" }).click();
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe(content);
  await expect(panel.getByRole("link", { name: "Local template" })).toHaveCount(
    0,
  );
  await expect(
    panel.getByText("Local template", { exact: true }),
  ).toBeVisible();
  await expect(panel.locator('img[src="images/flow.png"]')).toHaveCount(0);
  await panel.hover();
  await page.mouse.wheel(0, 15000);
  await expect(
    panel.getByRole("heading", { name: "End of snapshot" }),
  ).toBeInViewport();
  await expect(
    panel.getByRole("button", { name: "复制技能快照" }),
  ).toBeInViewport();
  await panel.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "使用的技能", exact: true }),
  ).toBeFocused();
});
