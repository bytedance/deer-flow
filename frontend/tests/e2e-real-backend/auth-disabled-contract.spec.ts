import { expect, test } from "@playwright/test";

import { AUTH_DISABLED_USER } from "../../src/core/auth/auth-disabled-user";

const APP =
  process.env.E2E_APP_URL ??
  `http://localhost:${process.env.E2E_FRONTEND_PORT ?? "3000"}`;

// /me also returns the caller's effective route permissions (RFC #4063
// Phase 4). Auth-disabled mode grants the full registered set, in the order
// of backend _ALL_PERMISSIONS (backend/app/gateway/authz.py).
const AUTH_DISABLED_PERMISSIONS = [
  "threads:read",
  "threads:write",
  "threads:delete",
  "runs:create",
  "runs:read",
  "runs:cancel",
];

test.describe("auth-disabled contract (real backend)", () => {
  test("gateway /auth/me returns the frontend synthetic user without a cookie", async ({
    context,
  }) => {
    const resp = await context.request.get(`${APP}/api/v1/auth/me`);

    expect(resp.status(), await resp.text()).toBe(200);
    await expect(resp.json()).resolves.toEqual({
      ...AUTH_DISABLED_USER,
      permissions: AUTH_DISABLED_PERMISSIONS,
    });
  });
});
