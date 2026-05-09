import { describe, expect, test } from "vitest";

import { MCP_PRESETS, getPresetById } from "@/core/mcp/presets";

describe("MCP_PRESETS catalog contract", () => {
  test("ships exactly the 5 expected presets", () => {
    expect(MCP_PRESETS.map((p) => p.id).sort()).toEqual([
      "filesystem",
      "gdrive",
      "github",
      "gmail",
      "notion",
    ]);
  });

  test("every preset has stable shape: id, displayName, description, authType", () => {
    for (const p of MCP_PRESETS) {
      expect(p.id).toMatch(/^[a-z][a-z0-9-]*$/);
      expect(p.displayName).toBeTruthy();
      expect(p.description.length).toBeGreaterThan(20);
      expect(["apiKey", "oauth", "none"]).toContain(p.authType);
    }
  });

  test("oauth presets declare an oauthProvider and have no fields to fill", () => {
    const oauth = MCP_PRESETS.filter((p) => p.authType === "oauth");
    expect(oauth.length).toBeGreaterThan(0);
    for (const p of oauth) {
      expect(p.oauthProvider).toBeTruthy();
      expect(p.fields).toEqual([]);
      // Backend builds the server config for OAuth; the helper must be absent.
      expect(p.toServerConfig).toBeUndefined();
    }
  });

  test("apiKey presets require at least one field and provide toServerConfig", () => {
    const apiKey = MCP_PRESETS.filter((p) => p.authType === "apiKey");
    expect(apiKey.length).toBeGreaterThan(0);
    for (const p of apiKey) {
      expect(p.fields.length).toBeGreaterThan(0);
      expect(p.fields.some((f) => f.required)).toBe(true);
      expect(typeof p.toServerConfig).toBe("function");
    }
  });

  test("getPresetById finds known ids and returns undefined otherwise", () => {
    expect(getPresetById("github")?.displayName).toBe("GitHub");
    expect(getPresetById("notion")?.authType).toBe("apiKey");
    expect(getPresetById("gmail")?.authType).toBe("oauth");
    expect(getPresetById("nonexistent-preset")).toBeUndefined();
  });
});

describe("MCP preset toServerConfig outputs", () => {
  test("github wires the PAT into GITHUB_PERSONAL_ACCESS_TOKEN", () => {
    const config = getPresetById("github")!.toServerConfig!({
      token: "github_pat_TESTTOKEN",
    });
    expect(config.enabled).toBe(true);
    expect(config.type).toBe("stdio");
    expect(config.command).toBe("npx");
    expect(config.args).toEqual(["-y", "@modelcontextprotocol/server-github"]);
    expect(config.env?.GITHUB_PERSONAL_ACCESS_TOKEN).toBe(
      "github_pat_TESTTOKEN",
    );
  });

  test("notion bakes the token into OPENAPI_MCP_HEADERS as a Bearer auth header", () => {
    const config = getPresetById("notion")!.toServerConfig!({
      token: "ntn_TESTTOKEN",
    });
    const headers = JSON.parse(config.env?.OPENAPI_MCP_HEADERS ?? "{}") as {
      Authorization: string;
      "Notion-Version": string;
    };
    expect(headers.Authorization).toBe("Bearer ntn_TESTTOKEN");
    expect(headers["Notion-Version"]).toBe("2022-06-28");
  });

  test("filesystem inlines the allowed directory as a positional CLI arg", () => {
    const config = getPresetById("filesystem")!.toServerConfig!({
      allowedPath: "/srv/data",
    });
    expect(config.args).toEqual([
      "-y",
      "@modelcontextprotocol/server-filesystem",
      "/srv/data",
    ]);
    // Filesystem MCP server is sandbox-scoped via the path arg, not env.
    expect(config.env).toEqual({});
  });

  test("missing required values do not throw — they pass through as empty strings", () => {
    // The form layer enforces 'required' before submit. The mapper must
    // still be defensive so a malformed call cannot crash the modal.
    expect(() =>
      getPresetById("github")!.toServerConfig!({}),
    ).not.toThrow();
    expect(
      getPresetById("github")!.toServerConfig!({}).env
        ?.GITHUB_PERSONAL_ACCESS_TOKEN,
    ).toBe("");
  });
});
