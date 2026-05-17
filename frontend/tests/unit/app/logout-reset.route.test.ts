import { describe, expect, test } from "vitest";

describe("logout-reset route", () => {
  test("clears the access_token cookie and redirects to the landing page", async () => {
    const { NextRequest } = await import("next/server");
    const { GET } = await import("@/app/logout-reset/route");

    const response = await GET(
      new NextRequest("http://localhost:2026/logout-reset"),
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:2026/");

    const setCookie = response.headers.get("set-cookie");
    expect(setCookie).toContain("access_token=");
    expect(setCookie).toContain("Max-Age=0");
    expect(setCookie).toContain("Path=/");
  });
});
