import { expect, test } from "@playwright/test";

/**
 * The default E2E config runs with auth disabled, so it cannot see this: the
 * standalone artifact window must stay reachable for a logged-out visitor when
 * the target is a public showcase artifact, and must not for anything else.
 */

// An allowlisted showcase artifact — see STATIC_DEMO_ARTIFACTS.
const DEMO_THREAD_ID = "3823e443-4e2b-4679-b496-a9506eae462b";
const DEMO_ARTIFACT = "/mnt/user-data/outputs/fei-fei-li-podcast-timeline.md";

function viewerUrl(params: Record<string, string>) {
  return `/artifacts/view?${new URLSearchParams(params).toString()}`;
}

test.describe("standalone artifact viewer access", () => {
  test("renders a public showcase artifact without a session", async ({
    page,
  }) => {
    await page.goto(
      viewerUrl({
        path: DEMO_ARTIFACT,
        thread_id: DEMO_THREAD_ID,
        mock: "true",
      }),
    );

    await expect(page).toHaveURL(/\/artifacts\/view/);
    await expect(
      page.getByText("fei-fei-li-podcast-timeline.md").first(),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("h1").first()).toBeVisible({ timeout: 15_000 });
  });

  test("sends a logged-out visitor to login for a non-public artifact", async ({
    page,
  }) => {
    await page.goto(
      viewerUrl({
        path: "/mnt/user-data/outputs/private-notes.md",
        thread_id: DEMO_THREAD_ID,
        mock: "true",
      }),
    );

    await expect(page).toHaveURL(/\/login\?next=/, { timeout: 15_000 });
  });

  test("sends a logged-out visitor to login when the mock flag is absent", async ({
    page,
  }) => {
    await page.goto(
      viewerUrl({ path: DEMO_ARTIFACT, thread_id: DEMO_THREAD_ID }),
    );

    await expect(page).toHaveURL(/\/login\?next=/, { timeout: 15_000 });
  });
});
