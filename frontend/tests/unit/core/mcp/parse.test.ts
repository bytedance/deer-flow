import { describe, expect, it } from "@rstest/core";

import {
  formatMCPServerDefinition,
  MCPServerDefinitionError,
  type MCPServerDefinitionErrorCode,
  parseMCPServerDefinition,
} from "@/core/mcp/parse";

function expectDefinitionError(
  input: string,
  code: MCPServerDefinitionErrorCode,
) {
  try {
    parseMCPServerDefinition(input);
    throw new Error("Expected the definition to be rejected");
  } catch (error) {
    expect(error).toBeInstanceOf(MCPServerDefinitionError);
    expect((error as MCPServerDefinitionError).code).toBe(code);
  }
}

describe("formatMCPServerDefinition", () => {
  it("serializes one complete server into the wrapped edit format", () => {
    const definition = formatMCPServerDefinition("remote", {
      enabled: false,
      description: "Remote tools",
      type: "http",
      url: "https://example.test/mcp",
      headers: { Authorization: "***" },
    });

    expect(JSON.parse(definition)).toEqual({
      mcpServers: {
        remote: {
          enabled: false,
          description: "Remote tools",
          type: "http",
          url: "https://example.test/mcp",
          headers: { Authorization: "***" },
        },
      },
    });
  });
});

describe("parseMCPServerDefinition", () => {
  it("accepts the wrapped form servers publish in their README", () => {
    const parsed = parseMCPServerDefinition(`{
      "mcpServers": {
        "github": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-github"]
        }
      }
    }`);

    expect(Object.keys(parsed)).toEqual(["github"]);
    expect(parsed.github).toMatchObject({
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-github"],
    });
  });

  it("accepts a bare server map", () => {
    const parsed = parseMCPServerDefinition(
      `{"remote": {"type": "http", "url": "https://example.test/mcp"}}`,
    );

    expect(Object.keys(parsed)).toEqual(["remote"]);
    expect(parsed.remote).toMatchObject({
      type: "http",
      url: "https://example.test/mcp",
    });
  });

  it("accepts a bare server named mcpServers", () => {
    const parsed = parseMCPServerDefinition(
      `{"mcpServers": {"command": "npx"}}`,
    );

    expect(parsed.mcpServers).toMatchObject({
      command: "npx",
      enabled: true,
    });
  });

  it("accepts an existing empty server name", () => {
    const parsed = parseMCPServerDefinition(`{"": {"command": "npx"}}`);

    expect(parsed[""]).toMatchObject({ command: "npx", enabled: true });
  });

  it("enables a pasted server by default", () => {
    const parsed = parseMCPServerDefinition(`{"a": {"command": "uvx"}}`);

    expect(parsed.a?.enabled).toBe(true);
  });

  it("keeps an explicit enabled flag from the definition", () => {
    const parsed = parseMCPServerDefinition(
      `{"a": {"command": "uvx", "enabled": false}}`,
    );

    expect(parsed.a?.enabled).toBe(false);
  });

  it("preserves fields this page never renders", () => {
    const parsed = parseMCPServerDefinition(`{
      "a": {
        "command": "uvx",
        "task_toolsets": [{"submit": "run"}],
        "routing": {"mode": "prefer"}
      }
    }`);

    expect(parsed.a).toMatchObject({
      task_toolsets: [{ submit: "run" }],
      routing: { mode: "prefer" },
    });
  });

  it("accepts multiple servers in one definition", () => {
    const parsed = parseMCPServerDefinition(
      `{"mcpServers": {"a": {"command": "npx"}, "b": {"command": "uvx"}}}`,
    );

    expect(Object.keys(parsed).sort()).toEqual(["a", "b"]);
  });

  it("rejects blank input", () => {
    expectDefinitionError("   ", "emptyDefinition");
  });

  it("rejects invalid JSON", () => {
    expectDefinitionError("{not json", "invalidJson");
  });

  it("rejects a non-object payload", () => {
    expectDefinitionError("[1, 2]", "rootNotObject");
  });

  it("rejects an empty server map", () => {
    expectDefinitionError(`{"mcpServers": {}}`, "emptyServerMap");
  });

  it("rejects a server entry that is not an object", () => {
    expectDefinitionError(`{"a": "npx"}`, "serverConfigNotObject");
  });

  it("rejects a non-object mcpServers value", () => {
    expectDefinitionError(`{"mcpServers": []}`, "serverConfigNotObject");
  });
});
