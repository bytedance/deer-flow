import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const threadId = "00000000-0000-0000-0000-000000009812";
const names = ["navigation.xlsx"];
const qa = path.resolve("test-results/file-transfer");

async function setup(page: Page) {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.addInitScript(() => localStorage.setItem("theme", "light"));
  const files = names.map((name) => `/mnt/user-data/outputs/${name}`);
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: threadId,
        title: "File transfer review",
        artifacts: files,
        messages: [
          { type: "human", id: "ask", content: "Review these files" },
          {
            type: "ai",
            id: "ready",
            content: "Files are ready.",
            tool_calls: [
              {
                id: "present",
                name: "present_files",
                args: { filepaths: files },
              },
            ],
          },
        ],
      },
    ],
  });
  await page.goto(`/workspace/chats/${threadId}`);
  await expect(page.getByText("Files are ready.")).toBeVisible();
  await mkdir(qa, { recursive: true });
}

test("single download displays preparation, suppresses repeated requests and retries a failure", async ({
  page,
}) => {
  await setup(page);
  let attempts = 0;
  let release!: () => void;
  await page.route(
    `**/api/threads/${threadId}/artifacts/**?download=true`,
    async (route) => {
      attempts++;
      if (attempts === 1) {
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        await route.fulfill({ status: 500, body: "download unavailable" });
      } else
        await route.fulfill({
          body: "download fixture",
          contentType: "application/octet-stream",
        });
    },
  );
  const button = page.getByRole("button", {
    name: `Download ${names[0]}`,
    exact: true,
  });
  await button.click();
  await expect(
    page.getByRole("button", {
      name: `Preparing download… ${names[0]}`,
      exact: true,
    }),
  ).toBeDisabled();
  await expect.poll(() => attempts).toBe(1);
  await page.screenshot({
    path: path.join(qa, "single-download-preparing-light.png"),
    animations: "disabled",
  });
  release();
  const retry = page.getByRole("button", {
    name: `Retry download ${names[0]}`,
    exact: true,
  });
  await expect(retry).toBeVisible();
  await page.screenshot({
    path: path.join(qa, "single-download-error-light.png"),
    animations: "disabled",
  });
  const download = page.waitForEvent("download");
  await retry.click();
  expect((await download).suggestedFilename()).toBe(names[0]);
  expect(attempts).toBe(2);
});

test("uploads retain successful files, cancel one file and retry only the failed file before explicit send", async ({
  page,
}) => {
  await setup(page);
  const attempts: string[] = [];
  const releases = new Map<string, () => void>();
  let sends = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname.endsWith("/runs/stream")
    )
      sends++;
  });
  await page.route(`**/api/threads/${threadId}/uploads`, async (route) => {
    const filename = /filename="([^"]+)"/.exec(
      route.request().postDataBuffer()!.toString(),
    )![1]!;
    attempts.push(filename);
    if (
      filename !== "success.txt" &&
      attempts.filter((name) => name === filename).length === 1
    ) {
      await new Promise<void>((resolve) => releases.set(filename, resolve));
      await route
        .fulfill({ status: 500, json: { detail: "Synthetic upload failure" } })
        .catch(() => {
          // A cancelled request may have disconnected before the fixture responds.
        });
      return;
    }
    await route.fulfill({
      json: {
        success: true,
        skipped_files: [],
        message: "Uploaded",
        files: [
          {
            filename,
            size: 8,
            path: `/uploads/${filename}`,
            virtual_path: `/mnt/user-data/uploads/${filename}`,
            artifact_url: `/api/threads/${threadId}/artifacts/mnt/user-data/uploads/${filename}`,
          },
        ],
      },
    });
  });
  const prompt = page
    .locator("form")
    .filter({ has: page.locator('textarea[name="message"]') });
  await page.getByLabel("Upload files").setInputFiles(
    ["success.txt", "retry.txt", "cancel.txt"].map((name) => ({
      name,
      mimeType: "text/plain",
      buffer: Buffer.from("fixture"),
    })),
  );
  await expect(prompt.getByRole("status")).toHaveText([
    "Ready to send",
    "Ready to send",
    "Ready to send",
  ]);
  await page
    .locator('textarea[name="message"]')
    .fill("Review these attachments");
  await prompt.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => attempts.length).toBe(3);
  await expect(prompt.getByRole("status")).toHaveText([
    "Uploaded",
    "Uploading…",
    "Uploading…",
  ]);
  await page.mouse.move(30, 30);
  await page.screenshot({
    path: path.join(qa, "uploads-in-progress-light.png"),
    animations: "disabled",
  });
  await prompt
    .getByRole("button", { name: "Cancel upload: cancel.txt", exact: true })
    .click();
  releases.get("retry.txt")!();
  releases.get("cancel.txt")!();
  await expect(prompt.getByRole("status")).toHaveText([
    "Uploaded",
    "Upload failed",
    "Cancelled",
  ]);
  await page.mouse.move(30, 30);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await expect(page.locator('textarea[name="message"]')).toHaveValue(
    "Review these attachments",
  );
  expect(sends).toBe(0);
  await page.screenshot({
    path: path.join(qa, "uploads-partial-failure-light.png"),
    animations: "disabled",
  });
  await prompt
    .getByRole("button", { name: "Retry upload: retry.txt", exact: true })
    .click();
  await expect(prompt.getByRole("status")).toHaveText([
    "Uploaded",
    "Uploaded",
    "Cancelled",
  ]);
  expect(attempts).toEqual([
    "success.txt",
    "retry.txt",
    "cancel.txt",
    "retry.txt",
  ]);
  expect(sends).toBe(0);
  await prompt
    .getByRole("button", { name: "Remove attachment: cancel.txt", exact: true })
    .click();
  await page.screenshot({
    path: path.join(qa, "uploads-recovered-light.png"),
    animations: "disabled",
  });
  await prompt.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => sends).toBe(1);
  await expect(prompt.getByTitle("success.txt", { exact: true })).toHaveCount(
    0,
  );
  expect(attempts.filter((name) => name === "success.txt")).toHaveLength(1);
});

test("installs an uploaded Skill from its chat card with the original path", async ({
  page,
}) => {
  const filename = "分析.skill";
  const virtualPath = `/mnt/user-data/uploads/${filename}`;
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: threadId,
        title: "Install uploaded Skill",
        messages: [
          {
            type: "human",
            id: "upload",
            content: "Install this Skill package",
            additional_kwargs: {
              files: [
                { filename, size: 512, path: virtualPath, status: "uploaded" },
              ],
            },
          },
        ],
      },
    ],
  });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.addInitScript(() => localStorage.setItem("theme", "light"));
  let attempts = 0;
  let installed = false;
  let release!: () => void;
  await page.route("**/api/skills", (route) =>
    route.fulfill({
      json: {
        skills: installed
          ? [
              {
                name: "analysis",
                description: "Uploaded analysis skill",
                category: "custom",
                license: "MIT",
                enabled: true,
                editable: true,
              },
            ]
          : [],
      },
    }),
  );
  await page.route("**/api/skills/install", async (route) => {
    attempts++;
    expect(route.request().postDataJSON()).toEqual({
      thread_id: threadId,
      path: virtualPath,
    });
    if (attempts === 1) {
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      await route.fulfill({
        status: 400,
        json: { detail: "Archive rejected by security review" },
      });
    } else {
      installed = true;
      await route.fulfill({
        json: {
          success: true,
          skill_name: "analysis",
          message: "Installed analysis",
        },
      });
    }
  });
  await page.goto(`/workspace/chats/${threadId}`);
  const button = page.getByRole("button", {
    name: `Install ${filename}`,
    exact: true,
  });
  await expect(button).toBeVisible();
  expect(attempts).toBe(0);
  await mkdir(qa, { recursive: true });
  await page.screenshot({
    path: path.join(qa, "uploaded-skill-light.png"),
    animations: "disabled",
  });
  await button.click();
  try {
    await expect(button).toBeDisabled();
    await expect.poll(() => attempts).toBe(1);
    await page.evaluate(() => document.documentElement.classList.add("dark"));
    await page.screenshot({
      path: path.join(qa, "uploaded-skill-pending-dark.png"),
      animations: "disabled",
    });
  } finally {
    release?.();
  }
  await expect(
    page.getByText("Archive rejected by security review", { exact: true }),
  ).toBeVisible();
  await expect(button).toBeEnabled();
  await button.click();
  await expect(
    page.getByText("Installed analysis", { exact: true }),
  ).toBeVisible();
  expect(attempts).toBe(2);
  const composer = page.getByRole("textbox", { name: /how can i assist you/i });
  await composer.fill("@analysis");
  await expect(
    page.getByRole("option", { name: "analysis Uploaded analysis skill" }),
  ).toBeVisible();
});

for (const tag of ["current_uploads", "uploaded_files"]) {
  test(`keeps a ${tag} text attachment preview-only`, async ({ page }) => {
    const filename = "compat.skill";
    const virtualPath = `/mnt/user-data/uploads/${filename}`;
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: threadId,
          title: "Compatibility attachment",
          messages: [
            {
              type: "human",
              id: "compat",
              content: `<${tag}>\n- ${filename} (512 B)\n  Path: ${virtualPath}\n</${tag}>`,
            },
          ],
        },
      ],
    });
    let installs = 0;
    await page.route("**/api/skills/install", async (route) => {
      installs++;
      await route.fulfill({
        status: 403,
        json: { detail: "Unexpected installation" },
      });
    });
    await page.route(`**/api/threads/${threadId}/artifacts/**`, (route) =>
      route.fulfill({ contentType: "text/plain", body: "Preview fixture" }),
    );
    await page.goto(`/workspace/chats/${threadId}`);
    await expect(
      page.getByRole("button", { name: `Install ${filename}`, exact: true }),
    ).toHaveCount(0);
    await page
      .getByRole("button", { name: `${filename} SKILL · 0.5 KB`, exact: true })
      .click();
    await expect(
      page.getByText("Preview fixture", { exact: true }),
    ).toBeVisible();
    expect(installs).toBe(0);
  });
}
