import { expect, test } from "@playwright/test";

// #3909 — in a full deployment (anything that is not the static marketing
// website), the root path must route the visitor straight into the app instead
// of showing what looks like the official website.
//
// This spec runs against the full-deployment e2e server (port 3000), which is
// started with DEER_FLOW_AUTH_DISABLED=1. That makes getServerSideUser() resolve
// to "authenticated", so `/` must redirect to `/workspace`.
//
// Note: the "unauthenticated -> /login" branch uses the exact same redirect()
// call and is covered by the same code path; it can only be exercised in e2e
// when the gateway returns no session (401) or is unreachable, which the e2e
// container does not provide while DEER_FLOW_AUTH_DISABLED=1 is set.
test.describe("Root path redirects into the app (full deployment)", () => {
  test("authenticated visitor is redirected from / to /workspace", async ({
    page,
  }) => {
    await page.goto("/");
    await page.waitForURL("**/workspace**");
    await expect(page).toHaveURL(/\/workspace/);
  });

  test("the visitor is not left on the marketing landing", async ({ page }) => {
    await page.goto("/");
    await page.waitForURL("**/workspace**");
    // After the redirect the URL is no longer the root path.
    await expect(page).not.toHaveURL(/\/$/);
  });
});
