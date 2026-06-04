import { afterEach, describe, expect, test, vi } from "vitest";

import { getAllowedDevOrigins, hostnameOf } from "@/lib/dev-origins.mjs";

describe("hostnameOf", () => {
  test.each([
    ["http://127.0.0.1:2026", "127.0.0.1"],
    ["http://serverhost.example:2026", "serverhost.example"],
    ["192.168.1.5:2026", "192.168.1.5"], // bare host:port (no scheme)
    ["localhost", "localhost"],
    ["http://[::1]:2026", "[::1]"], // IPv6 keeps its brackets
    ["HTTP://Example.COM", "example.com"], // URL lowercases the host
  ])("parses %s -> %s", (input, expected) => {
    expect(hostnameOf(input)).toBe(expected);
  });

  test("returns null for blank or unparseable input", () => {
    expect(hostnameOf(undefined)).toBeNull();
    expect(hostnameOf(null)).toBeNull();
    expect(hostnameOf("")).toBeNull();
    expect(hostnameOf("http://")).toBeNull();
  });
});

describe("getAllowedDevOrigins", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  test("always allows 127.0.0.1 when no origins are configured", () => {
    expect(getAllowedDevOrigins(undefined)).toEqual(["127.0.0.1"]);
    expect(getAllowedDevOrigins("")).toEqual(["127.0.0.1"]);
  });

  test("derives hostnames from GATEWAY_CORS_ORIGINS and dedupes", () => {
    expect(
      getAllowedDevOrigins(
        "http://serverhost.example:2026,http://192.168.1.5:2026,http://serverhost.example:2026",
      ),
    ).toEqual(["127.0.0.1", "serverhost.example", "192.168.1.5"]);
  });

  test("skips '*' (aligns with backend CORS parser) and blank entries", () => {
    expect(getAllowedDevOrigins("*, ,http://serverhost.example:2026")).toEqual([
      "127.0.0.1",
      "serverhost.example",
    ]);
  });

  test("drops a scheme-qualified '*' (http://*) instead of adding '*'", () => {
    // hostnameOf("http://*") resolves to "*", which Next.js would not honour
    // as a wildcard; keep it out of the list so it never leaks in.
    expect(
      getAllowedDevOrigins("http://*,http://serverhost.example:2026"),
    ).toEqual(["127.0.0.1", "serverhost.example"]);
  });

  test("does not duplicate 127.0.0.1 when it is also configured", () => {
    expect(getAllowedDevOrigins("http://127.0.0.1:2026")).toEqual([
      "127.0.0.1",
    ]);
  });

  test("reads GATEWAY_CORS_ORIGINS from the environment by default", () => {
    vi.stubEnv("GATEWAY_CORS_ORIGINS", "http://env-host.example:2026");
    expect(getAllowedDevOrigins()).toEqual(["127.0.0.1", "env-host.example"]);
  });
});
