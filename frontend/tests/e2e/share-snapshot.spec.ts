import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

const token = "S".repeat(43);
const created = {
  share_id: "share-1",
  checkpoint_id: "cp-1",
  seq: 3,
  created_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 86400000).toISOString(),
  revoked_at: null,
};
const snapshot = {
  ...created,
  title: "Quarterly report",
  messages: [
    { id: "human", type: "human", content: "Compare quarterly revenue." },
    {
      id: "answer",
      type: "ai",
      content:
        "Revenue rose. [Report](sandbox:/mnt/user-data/outputs/report.html) ![tracking](https://tracker.invalid/pixel) [private](/workspace/chats/secret)",
    },
    { id: "tool", type: "tool", name: "python", content: "Revenue: 42" },
  ],
  artifacts: [
    {
      path: "report.html",
      mime_type: "text/html",
      size: 50,
      sha256: "a".repeat(64),
    },
    {
      path: "numbers.csv",
      mime_type: "text/csv",
      size: 23,
      sha256: "b".repeat(64),
    },
  ],
};

test("anonymous snapshot previews files without entering the private workspace", async ({
  page,
}, testInfo) => {
  const privateRequests: string[] = [];
  page.on("request", (request) => {
    if (
      /\/api\/(threads|langgraph|v1\/auth)/.test(request.url()) ||
      request.url().includes("tracker.invalid")
    )
      privateRequests.push(request.url());
  });
  let revoked = false;
  await page.route(`**/api/shares/${token}`, (route) =>
    route.fulfill({
      status: revoked ? 404 : 200,
      json: revoked ? {} : snapshot,
    }),
  );
  await page.route(`**/api/shares/${token}/artifacts/*`, (route) =>
    route.fulfill({
      contentType: route.request().url().endsWith(".csv")
        ? "text/csv"
        : "text/html",
      headers: {
        "Content-Security-Policy":
          "sandbox; default-src 'none'; style-src 'unsafe-inline'",
      },
      body: route.request().url().endsWith(".csv")
        ? "Quarter,Revenue\nQ1,42\n"
        : "<h1>Frozen report</h1><script>parent.document.body.innerHTML='unsafe'</script>",
    }),
  );
  await page.goto(`/share/${token}`);
  await expect(
    page.getByRole("heading", { name: "Quarterly report" }),
  ).toBeVisible();
  await expect(
    page.getByText("Read-only snapshot", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("textarea, [contenteditable=true]")).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "private", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Report", exact: true }),
  ).toHaveAttribute("href", `/api/shares/${token}/artifacts/report.html`);
  await page.getByRole("button", { name: "report.html", exact: true }).click();
  await expect(page.locator("iframe")).toHaveAttribute("sandbox", "");
  await expect(
    page.frameLocator("iframe").getByRole("heading", { name: "Frozen report" }),
  ).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await page.getByRole("button", { name: "numbers.csv", exact: true }).click();
  await expect(
    page.getByRole("dialog").getByText("42", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  expect(privateRequests).toEqual([]);
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.screenshot({
    path: testInfo.outputPath("share-preview.png"),
    fullPage: true,
  });
  revoked = true;
  await page.reload();
  await expect(
    page.getByText(
      "This share link has expired, was revoked, or is unavailable.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Continue in my workspace" }),
  ).toHaveCount(0);
});

test("anonymous Fork signs in and returns to the shared snapshot", async ({
  page,
}) => {
  await page.route(`**/api/shares/${token}`, (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({ status: 401, json: { detail: "Sign in" } }),
  );
  await page.route("**/login**", (route) =>
    route.fulfill({ contentType: "text/html", body: "Sign in" }),
  );
  let imports = 0;
  await page.route(`**/api/shares/${token}/fork`, (route) => {
    imports++;
    return route.fulfill({ json: { thread_id: "copy" } });
  });
  await page.goto(`/share/${token}`);
  await page.getByRole("button", { name: "Continue in my workspace" }).click();
  await expect(page).toHaveURL(new RegExp(`/login\\?next=.*share.*${token}`));
  expect(imports).toBe(0);
});

test("shared PDFs keep Chromium's native viewer enabled", async ({ page }) => {
  const stream = "BT /F1 12 Tf 20 100 Td (Shared PDF report) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = objects.map((object, index) => {
    const offset = pdf.length;
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
    return offset;
  });
  const xref = pdf.length;
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  await page.route(`**/api/shares/${token}`, (route) =>
    route.fulfill({
      json: {
        ...snapshot,
        artifacts: [
          {
            path: "report.pdf",
            mime_type: "application/pdf",
            size: pdf.length,
            sha256: "c".repeat(64),
          },
        ],
      },
    }),
  );
  await page.route(`**/api/shares/${token}/artifacts/report.pdf`, (route) =>
    route.fulfill({
      contentType: "application/pdf",
      headers: { "X-Content-Type-Options": "nosniff" },
      body: pdf,
    }),
  );
  await page.goto(`/share/${token}`);
  const response = page.waitForResponse((response) =>
    response.url().endsWith("/artifacts/report.pdf"),
  );
  await page.getByRole("button", { name: "report.pdf", exact: true }).click();
  expect((await response).headers()["content-type"]).toBe("application/pdf");
  await expect(page.getByRole("dialog").locator("iframe")).toBeVisible();
  await expect(page.getByRole("dialog").locator("iframe")).not.toHaveAttribute(
    "sandbox",
  );
});

test("authenticated Fork opens its new workspace conversation", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [{ thread_id: MOCK_THREAD_ID, title: "Imported report" }],
  });
  await page.route(`**/api/shares/${token}`, (route) =>
    route.fulfill({ json: snapshot }),
  );
  let requestId: string | undefined;
  await page.route(`**/api/shares/${token}/fork`, (route) => {
    requestId = (route.request().postDataJSON() as { request_id: string })
      .request_id;
    return route.fulfill({ json: { thread_id: MOCK_THREAD_ID } });
  });
  await page.goto(`/share/${token}`);
  await page.getByRole("button", { name: "Continue in my workspace" }).click();
  await expect(page).toHaveURL(`/workspace/chats/${MOCK_THREAD_ID}`, {
    timeout: 15000,
  });
  expect(requestId).toMatch(/^[0-9a-f-]{36}$/);
});

test("owner creates and revokes a snapshot from the sidebar", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page, {
    threads: [{ thread_id: MOCK_THREAD_ID, title: "Owner report" }],
  });
  await page.route(`**/api/threads/${MOCK_THREAD_ID}/shares`, (route) => {
    if (route.request().method() === "GET") return route.fulfill({ json: [] });
    expect(route.request().postDataJSON()).toEqual({
      expires_in_seconds: 3600,
    });
    return route.fulfill({
      status: 201,
      json: {
        ...created,
        token,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
      },
    });
  });
  await page.route(
    `**/api/threads/${MOCK_THREAD_ID}/shares/share-1`,
    (route) => {
      expect(route.request().method()).toBe("DELETE");
      return route.fulfill({ status: 204 });
    },
  );
  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  const row = page.locator('[data-sidebar="menu-item"]').filter({
    has: page.getByRole("link", { name: "Owner report", exact: true }),
  });
  await row.hover();
  await row.getByRole("button", { name: "More", exact: true }).click();
  await page.screenshot({
    path: testInfo.outputPath("share-menu.png"),
    fullPage: true,
  });
  await page.getByRole("menuitem", { name: "Share", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox").selectOption("3600");
  await dialog.getByRole("button", { name: "Create snapshot link" }).click();
  await expect(dialog.getByLabel("Share link")).toHaveValue(
    new RegExp(`/share/${token}$`),
  );
  await page.screenshot({
    path: testInfo.outputPath("share-entry.png"),
    fullPage: true,
  });
  await dialog.getByRole("button", { name: "Revoke", exact: true }).click();
  await expect(dialog.getByText("Revoked", { exact: true })).toBeVisible();
  await expect(dialog.getByLabel("Share link")).toHaveCount(0);
});
