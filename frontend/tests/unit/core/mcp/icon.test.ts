import { describe, expect, it } from "@rstest/core";

import {
  readPluginIcon,
  safePluginIcon,
  withPluginIcon,
} from "@/core/mcp/icon";

const png =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6Xl8AAAAASUVORK5CYII=";

describe("plugin icon metadata", () => {
  it("never displays a URL, SVG, malformed value, or oversized payload from server config", () => {
    for (const value of [
      "https://example.test/icon.png",
      "javascript:alert(1)",
      "data:image/svg+xml,<svg/>",
      {},
      "data:image/png;base64," + "A".repeat(100_000),
    ]) {
      expect(safePluginIcon(value)).toBeUndefined();
    }
    expect(safePluginIcon(png)).toBe(png);
  });

  it("preserves connection settings, secret placeholders, and unrelated metadata when replacing or removing an icon", () => {
    const server = {
      enabled: false,
      description: "Company CRM",
      url: "https://example.test/mcp",
      headers: { Authorization: "***" },
      presentation: { icon: png, display_name: "CRM" },
      vendor: { custom: true },
    };
    const updated = withPluginIcon(server, png);
    expect(readPluginIcon(updated)).toBe(png);
    expect(withPluginIcon(updated, null)).toEqual({
      ...server,
      presentation: { display_name: "CRM" },
    });
    expect(server.presentation.icon).toBe(png);
    expect(withPluginIcon(server, undefined)).toBe(server);
  });

  it("removes the empty presentation container on reset and rejects an unsafe replacement", () => {
    const server = {
      enabled: true,
      description: "",
      presentation: { icon: png },
    };
    expect(withPluginIcon(server, null)).toEqual({
      enabled: true,
      description: "",
    });
    expect(() => withPluginIcon(server, "https://example.test/logo")).toThrow();
  });
});
