import { describe, expect, it } from "@rstest/core";
import { NextRequest } from "next/server";

import { config, proxy } from "@/proxy";

/**
 * `NextResponse.next({ request: { headers } })` tells the Next server which
 * request headers to keep: it puts every key of the returned `Headers` into
 * `x-middleware-override-headers`, and the server deletes each incoming header
 * that is not in that list before dispatching to the route handler or rewrite.
 * Asserting on the override list is therefore the closest check to the wire
 * behavior without starting a server.
 */
function overriddenHeaders(response: Response): Set<string> {
  const raw = response.headers.get("x-middleware-override-headers") ?? "";
  return new Set(
    raw
      .split(",")
      .map((name) => name.trim())
      .filter(Boolean),
  );
}

describe("gateway internal trust headers", () => {
  it("are dropped from a request heading into a rewrite", () => {
    const request = new NextRequest("http://deer-flow.test/api/agents", {
      headers: {
        "x-deerflow-internal-token": "leaked-token",
        "x-deerflow-owner-user-id": "victim",
        "x-keep-me": "kept",
      },
    });

    const overridden = overriddenHeaders(proxy(request));

    expect(overridden.has("x-deerflow-internal-token")).toBe(false);
    expect(overridden.has("x-deerflow-owner-user-id")).toBe(false);
    // Anything else the client sent must survive: this strips two headers, it
    // does not rebuild the request.
    expect(overridden.has("x-keep-me")).toBe(true);
  });

  it("are dropped regardless of the casing the client used", () => {
    const request = new NextRequest(
      "http://deer-flow.test/api/langgraph/threads",
      {
        headers: {
          "X-DeerFlow-Internal-Token": "leaked-token",
          "X-DeerFlow-Owner-User-Id": "victim",
        },
      },
    );

    const overridden = overriddenHeaders(proxy(request));

    expect(overridden.has("x-deerflow-internal-token")).toBe(false);
    expect(overridden.has("x-deerflow-owner-user-id")).toBe(false);
  });

  it("are stripped on the whole /api rewrite surface", () => {
    // The matcher must not carve `/api/*` out: the rewrites in next.config.js
    // (/api/langgraph/*, /api/agents, /api/skills, catch-all /api/:path*) are
    // exactly the surface this file exists to cover.
    const matcher = config.matcher.join(" ");

    expect(matcher).not.toContain("api");
    expect(matcher).toContain("_next/");
    // No extension-based exclusion either: `/api/threads/<id>/artifacts/report.png`
    // goes through the same rewrite and must be stripped like any other path.
    expect(matcher).not.toMatch(/png|jpe?g|svg|woff/);
  });
});
