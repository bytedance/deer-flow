import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

test("the first project file reference keeps subsequent typing after the chip across thread handoff", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    skills: [{ name: "research", description: "Research", enabled: true }],
    projects: [{ id: "proj-1", name: "Research project" }],
    projectDocuments: [
      { id: "doc-1", project_id: "proj-1", name: "report.pdf", size_bytes: 10 },
    ],
  });
  await page.goto("/workspace/chats/new?project=proj-1");
  const input = page.getByRole("textbox", { name: /how can i assist you/i });
  await input.fill("Read @report");
  await page.getByRole("option", { name: "report.pdf", exact: true }).click();
  await expect(page.getByTestId("project-attachment-chip")).toContainText(
    "report.pdf",
  );
  await input.pressSequentially("summarize");
  await expect(input).toHaveText("Read ▤report.pdf summarize");
  await expect(page).not.toHaveURL(/\/new/);
  await page.reload();
  await expect(input).toHaveText("Read ▤report.pdf summarize");
  await expect(page.getByTestId("project-attachment-chip")).toContainText(
    "report.pdf",
  );
});
