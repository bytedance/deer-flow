import { readFile } from "node:fs/promises";
import path from "node:path";

import type { BrowserContext, Page } from "@playwright/test";

export const officeFixtures = path.resolve("tests/e2e/fixtures/office-preview");
export const officePackage = path.resolve(
  "../examples/deerflow-extension-office-preview/deerflow_extension_office_preview",
);

/** Serve the actual packaged browser module graph, including lazy parser chunks. */
export async function mockOfficePreview(page: Page | BrowserContext) {
  const manifest = JSON.parse(
    await readFile(path.join(officePackage, "ui_manifest.json"), "utf8"),
  ) as { entry: string; files: string[] };
  const prefix = `/api/plugins/office-preview/assets/${"a".repeat(64)}/`;
  await page.route("**/api/plugins", (route) =>
    route.fulfill({
      json: [
        {
          viewer_id: "default",
          namespace: "office-preview",
          module: "office-preview",
          entry: `${prefix}${manifest.entry}`,
          transport: "assets-v1",
          title: "Office preview",
          description: "",
          settings: { enabled: true },
        },
      ],
    }),
  );
  // Worker requests are owned by the context, rather than a Page route.
  const assets = "context" in page ? page.context() : page;
  await assets.route(
    "**/api/plugins/office-preview/assets/**",
    async (route) => {
      const filename = new URL(route.request().url()).pathname.slice(
        prefix.length,
      );
      if (!manifest.files.includes(filename))
        return route.fulfill({ status: 404 });
      return route.fulfill({
        contentType: "text/javascript",
        headers: { "Content-Security-Policy": "sandbox" },
        body: await readFile(path.join(officePackage, filename)),
      });
    },
  );
}
