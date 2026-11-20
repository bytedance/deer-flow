import { expect, test, type APIRequestContext } from "@playwright/test";
import { z } from "zod";

const APP =
  process.env.E2E_APP_URL ??
  `http://localhost:${process.env.E2E_FRONTEND_PORT ?? "3000"}`;

// Copy and assertions are the English ones; pin the browser locale so the
// frontend's i18n resolution cannot drift with the CI machine.
test.use({ locale: "en-US" });

// Gateway response shapes this spec depends on (parsed once at the boundary).
const CreatedProject = z.object({ id: z.string() });
const UploadedDocument = z.object({ document: z.object({ id: z.string() }) });
const TrashListing = z.object({
  documents: z.array(z.object({ id: z.string() })),
});

/**
 * Layer 2 (front-back contract): "Empty trash" has to delete exactly what its
 * confirmation lists.
 *
 * A freshly trashed document sits far inside the retention window, so nothing
 * can delete it except the action itself — the retention sweep only reclaims
 * expired rows. Setup goes through the same-origin proxy the UI uses (real
 * gateway, real SQLite, real filesystem); the action under test is the button
 * click and its effect on the gateway's state.
 */
async function seedTrashedDocument(
  request: APIRequestContext,
  name: string,
): Promise<string> {
  const created = await request.post(`${APP}/api/projects`, {
    data: { name: `e2e-trash-${name}` },
  });
  expect(created.status(), await created.text()).toBe(201);
  const projectId = CreatedProject.parse(await created.json()).id;

  const uploaded = await request.post(
    `${APP}/api/projects/${projectId}/documents`,
    {
      multipart: {
        file: {
          name,
          mimeType: "text/plain",
          buffer: Buffer.from("freshly trashed bytes"),
        },
      },
    },
  );
  expect(uploaded.status(), await uploaded.text()).toBe(201);
  const documentId = UploadedDocument.parse(await uploaded.json()).document.id;

  const trashed = await request.delete(
    `${APP}/api/projects/${projectId}/documents/${documentId}`,
  );
  expect(trashed.status(), await trashed.text()).toBe(204);
  return documentId;
}

async function listedTrashIds(request: APIRequestContext): Promise<string[]> {
  const listing = await request.get(`${APP}/api/trash/documents`);
  expect(listing.status(), await listing.text()).toBe(200);
  return TrashListing.parse(await listing.json()).documents.map(
    (document) => document.id,
  );
}

test.describe("trash empty action (real backend)", () => {
  test("Empty trash permanently deletes a freshly trashed document", async ({
    page,
    context,
  }) => {
    const name = `e2e-trash-${Date.now()}.txt`;
    const documentId = await seedTrashedDocument(context.request, name);

    await page.goto("/workspace/trash", { waitUntil: "domcontentloaded" });
    await expect(page.getByText(name, { exact: true })).toBeVisible();

    await page.getByTestId("trash-empty-button").click();
    // Count-agnostic: the test owns one row, but the trash view (and thus the
    // confirmation) covers every trashed row the account has.
    await expect(
      page.getByText(
        /documents? will be permanently deleted\. This cannot be undone\./,
      ),
    ).toBeVisible();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Empty trash", exact: true })
      .click();

    // The row leaves the view and the gateway's trash for good: the
    // confirmation promised permanent deletion, not a retention wait.
    await expect(page.getByText(name, { exact: true })).toHaveCount(0);
    await expect
      .poll(
        async () =>
          (await listedTrashIds(context.request)).includes(documentId),
        {
          message: "the purged row must be gone from GET /api/trash/documents",
        },
      )
      .toBe(false);
  });
});
