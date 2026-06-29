import { describe, expect, test } from "vitest";

import { resolveAuthError } from "@/core/auth/api-error";

describe("resolveAuthError", () => {
  test("redirects only true session expiry as expired login", () => {
    const result = resolveAuthError(
      {
        status: 401,
        detail: {
          code: "token_expired",
          message: "Token expired",
        },
      },
      "发布",
    );

    expect(result).toEqual({
      code: "token_expired",
      message: "登录已过期，请重新登录后再发布",
      shouldRedirect: true,
    });
  });

  test("treats generic unauthenticated responses as auth state issues, not expiry", () => {
    const result = resolveAuthError(
      {
        status: 401,
        detail: {
          code: "not_authenticated",
          message: "Authentication required",
        },
      },
      "发布",
    );

    expect(result).toEqual({
      code: "not_authenticated",
      message: "登录状态异常，请重新登录后再发布",
      shouldRedirect: true,
    });
  });

  test("surfaces upstream auth outages without logging the user out", () => {
    const result = resolveAuthError(
      {
        status: 401,
        detail: {
          code: "provider_unavailable",
          message: "Authentication service unavailable",
        },
      },
      "发布",
    );

    expect(result).toEqual({
      code: "provider_unavailable",
      message: "Authentication service unavailable",
      shouldRedirect: false,
    });
  });

  test("ignores non-auth errors", () => {
    expect(resolveAuthError({ status: 403 }, "发布")).toBeNull();
    expect(resolveAuthError(new Error("boom"), "发布")).toBeNull();
  });
});
