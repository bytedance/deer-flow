import { expect, test } from "@playwright/test";

import type { MailDraft } from "@/core/enterprise/mail-outbox";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

test("compose, reopen the AI review link and explicitly submit one immutable draft", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  let draft: MailDraft | undefined;
  let submitted = 0;
  await page.route("**/api/enterprise{,/**}", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/mail/drafts") && request.method() === "POST") {
      const input = request.postDataJSON();
      expect(input).toEqual({
        account_id: "mail1",
        to: ["bob@example.com"],
        cc: ["carol@example.com"],
        subject: "会议安排",
        body: "请查收明天下午的会议安排。",
      });
      draft = {
        ...input,
        id: "draft1",
        sender: "alice@example.com",
        status: "draft",
        result: null,
        message_id: "<draft1@example.com>",
        created_at: "2026-10-20 01:00:00",
      };
      return route.fulfill({ json: draft });
    }
    if (path.endsWith("/mail/drafts"))
      return route.fulfill({ json: { drafts: draft ? [draft] : [] } });
    if (path.endsWith("/mail/drafts/draft1/send")) {
      expect(request.method()).toBe("POST");
      expect(request.postDataJSON()).toEqual({ confirmed: true });
      submitted++;
      draft = {
        ...draft!,
        status: "sent",
        result: {
          error: null,
          accepted: ["bob@example.com", "carol@example.com"],
          refused: [],
        },
      };
      return route.fulfill({ json: draft });
    }
    if (path.endsWith("/mail/drafts/draft1")) {
      expect(request.method()).toBe("GET");
      return route.fulfill({ json: draft });
    }
    if (path.endsWith("/mail"))
      return route.fulfill({
        json: {
          accounts: [
            { id: "mail1", name: "Office", provider: "alimail", enabled: true },
          ],
        },
      });
    return route.fulfill({
      json: { targets: [], deliveries: [], scheduler_enabled: true },
    });
  });
  await page.goto("/workspace/enterprise");
  await page.getByRole("button", { name: "Compose email" }).click();
  await page.getByLabel("To", { exact: true }).fill("bob@example.com");
  await page.getByLabel("Cc (optional)").fill("carol@example.com");
  await page.getByLabel("Subject", { exact: true }).fill("会议安排");
  await page
    .getByLabel("Body", { exact: true })
    .fill("请查收明天下午的会议安排。");
  await page.getByRole("button", { name: "Save and preview" }).click();
  await expect(
    page.getByRole("region", { name: "Email preview" }),
  ).toBeVisible();
  expect(submitted).toBe(0);
  await page.goto("/workspace/enterprise?mail_draft=draft1");
  const preview = page.getByRole("region", { name: "Email preview" });
  await expect(preview.getByText("alice@example.com")).toBeVisible();
  await expect(
    preview.getByRole("button", { name: "Confirm and send" }),
  ).toBeDisabled();
  await preview.screenshot({
    path: test.info().outputPath("mail-compose-preview.png"),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await preview.getByRole("checkbox").check();
  await preview.getByRole("button", { name: "Confirm and send" }).click();
  await expect(preview.getByRole("status")).toHaveText("Submitted");
  expect(submitted).toBe(1);
  await page.getByRole("button", { name: "Refresh status" }).click();
  expect(submitted).toBe(1);
});

test("connect, preview, pagination and AI analysis preserve messages", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  let connected = false;
  let reads = 0;
  await page.route("**/api/enterprise{,/**}", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/mail/accounts")) {
      expect(request.postDataJSON()).toMatchObject({
        email: "test@example.com",
        password: "synthetic-client-password",
        host: "imap.qiye.aliyun.com",
      });
      connected = true;
      await route.fulfill({ json: { id: "mail1" } });
    } else if (url.pathname.endsWith("/mail")) {
      await route.fulfill({
        json: {
          accounts: connected
            ? [
                {
                  id: "mail1",
                  name: "Office",
                  provider: "alimail",
                  enabled: true,
                },
              ]
            : [],
        },
      });
    } else if (url.pathname.endsWith("/messages")) {
      expect(request.method()).toBe("GET");
      reads++;
      if (reads === 2) {
        expect(url.searchParams.get("before_uid")).toBe("20");
        expect(url.searchParams.get("uidvalidity")).toBe("123");
      }
      await route.fulfill({
        json: {
          messages: [
            {
              uid: reads === 1 ? 20 : 10,
              subject: reads === 1 ? "Invoice October" : "Older invoice",
              sender: "Supplier <test@example.com>",
              date: "2026-10-09",
              unread: true,
              text: "Please review the invoice. <img src=x onerror=alert(1)>",
              category: "finance",
              attachments: ["invoice.pdf"],
              truncated: false,
            },
          ],
          has_more: reads === 1,
          next_before_uid: reads === 1 ? 20 : null,
          uidvalidity: "123",
        },
      });
    } else {
      await route.fulfill({
        json: { targets: [], deliveries: [], scheduler_enabled: true },
      });
    }
  });
  await page.route("**/threads", async (route) => {
    if (route.request().method() === "POST")
      await route.fulfill({ json: { thread_id: MOCK_THREAD_ID } });
    else await route.fallback();
  });
  let runCount = 0;
  await page.route(`**/threads/${MOCK_THREAD_ID}/runs`, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    runCount++;
    const body = route.request().postDataJSON() as {
      input: { messages: { content: string }[] };
    };
    expect(body.input.messages[0]?.content).toContain('"account_id":"mail1"');
    expect(JSON.stringify(body)).not.toContain("synthetic-client-password");
    await route.fulfill({ status: 503, json: { detail: "synthetic failure" } });
  });
  await page.goto("/workspace/enterprise");
  await page
    .getByRole("button", { name: "Connect mailbox", exact: true })
    .click();
  await page.getByLabel("Mailbox name", { exact: true }).fill("Office");
  await page
    .getByLabel("Email address", { exact: true })
    .fill("test@example.com");
  await page
    .getByLabel("Email password", { exact: true })
    .fill("synthetic-client-password");
  await page.getByRole("button", { name: "Verify and connect" }).click();
  await expect(page.getByLabel("Email password")).toHaveCount(0);
  await page.getByRole("button", { name: "Read and preview" }).click();
  await expect(
    page.getByText("Invoice October", { exact: true }),
  ).toBeVisible();
  await page.getByText("Invoice October", { exact: true }).click();
  await expect(
    page.getByText("Please review the invoice.", { exact: false }),
  ).toBeVisible();
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  await page.getByRole("button", { name: "Read older emails" }).click();
  await expect(page.getByText("Older invoice", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Organize with AI" }).click();
  await expect(
    page.getByRole("link", { name: "Open analysis chat" }),
  ).toHaveAttribute("href", `/workspace/chats/${MOCK_THREAD_ID}`);
  await expect(
    page.getByRole("button", { name: "Organize with AI" }),
  ).toBeDisabled();
  expect(runCount).toBe(1);
  await page.screenshot({ path: test.info().outputPath("mail-preview.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("mail permission error is independent from WeCom access", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  await page.route("**/api/enterprise{,/**}", async (route) => {
    if (new URL(route.request().url()).pathname.endsWith("/mail")) {
      await route.fulfill({
        status: 403,
        json: { detail: { code: "access_denied" } },
      });
    } else
      await route.fulfill({
        json: { targets: [], deliveries: [], scheduler_enabled: true },
      });
  });
  await page.goto("/workspace/enterprise");
  await expect(
    page
      .getByRole("region", { name: "Alibaba enterprise mail" })
      .getByRole("alert"),
  ).toContainText("enterprise_mail");
  await expect(
    page.getByRole("button", { name: "Connect mailbox", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Bind group", exact: true }),
  ).toBeEnabled();
});

test("AI organization opens the newly created chat after a successful launch", async ({
  page,
}) => {
  // The successful run fixture must also expose the created chat's input.
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        messages: [
          {
            id: "mail-analysis-input",
            type: "human",
            content: "Organize my inbox.",
          },
        ],
      },
    ],
  });
  await page.route("**/api/enterprise{,/**}", async (route) => {
    await route.fulfill({
      json: new URL(route.request().url()).pathname.endsWith("/mail")
        ? {
            accounts: [
              {
                id: "mail1",
                name: "Office",
                provider: "alimail",
                enabled: true,
              },
            ],
          }
        : { targets: [], deliveries: [], scheduler_enabled: true },
    });
  });
  await page.route("**/threads", async (route) => {
    if (route.request().method() === "POST")
      await route.fulfill({ json: { thread_id: MOCK_THREAD_ID } });
    else await route.fallback();
  });
  await page.route(`**/threads/${MOCK_THREAD_ID}/runs`, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    expect(route.request().postDataJSON()).toMatchObject({
      assistant_id: "lead_agent",
      config: { recursion_limit: 1000 },
      stream_mode: ["messages-tuple", "updates", "custom"],
    });
    await route.fulfill({
      json: {
        run_id: "test-run",
        thread_id: MOCK_THREAD_ID,
        status: "pending",
      },
    });
  });
  await page.goto("/workspace/enterprise");
  await page.getByRole("button", { name: "Organize with AI" }).click();
  await expect(page).toHaveURL(
    new RegExp(`/workspace/chats/${MOCK_THREAD_ID}$`),
  );
});
