import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("knowledge upload and parse retry preserve the uploaded document", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  let uploaded = false;
  let parsed = false;
  const file = {
    id: "doc1",
    name: "knowledge-smoke.txt",
    size: 26,
    chunk_count: 0,
    progress: 0,
    status: "pending",
  };
  await page.route("**/api/knowledge-base/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/parse")) {
      parsed = true;
      await route.fulfill({ json: { parsing_started: true } });
    } else if (path.endsWith("/documents") && request.method() === "POST") {
      expect(request.headers()["content-type"]).toContain(
        "multipart/form-data",
      );
      expect(request.postDataBuffer()?.toString()).toContain(
        "Synthetic knowledge sample",
      );
      uploaded = true;
      await route.fulfill({
        json: { documents: [file], parsing_started: false },
      });
    } else if (path.endsWith("/documents")) {
      await route.fulfill({
        json: {
          documents: uploaded
            ? [{ ...file, status: parsed ? "parsing" : "pending" }]
            : [],
          total: uploaded ? 1 : 0,
        },
      });
    } else {
      await route.fulfill({
        json: {
          datasets: [
            {
              id: "ds1",
              name: "Team knowledge",
              document_count: 0,
              chunk_count: 0,
            },
          ],
          can_upload: true,
          can_create: true,
          max_file_bytes: 52428800,
        },
      });
    }
  });
  await page.goto("/workspace/knowledge-base");
  await expect(
    page.getByRole("heading", { name: "Knowledge base", exact: true }),
  ).toBeVisible();
  await page
    .locator("input[type=file]")
    .setInputFiles({
      name: file.name,
      mimeType: "text/plain",
      buffer: Buffer.from("Synthetic knowledge sample"),
    });
  await expect(
    page.getByText(/Uploaded, but parsing did not start/),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Start parsing", exact: true })
    .click();
  await expect(page.getByRole("cell", { name: "Parsing 0%" })).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("knowledge-base-desktop.png"),
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Knowledge base", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
