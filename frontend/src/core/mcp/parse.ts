import type { MCPServerConfig } from "./types";

/** A pasted definition that is not a usable `mcpServers` map. */
export class MCPServerDefinitionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MCPServerDefinitionError";
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Serialize one existing server into the same copy-paste format the parser accepts. */
export function formatMCPServerDefinition(
  name: string,
  config: MCPServerConfig,
): string {
  return JSON.stringify({ mcpServers: { [name]: config } }, null, 2);
}

/**
 * Parse the JSON block an MCP server publishes in its own README.
 *
 * Both the wrapped form (`{"mcpServers": {...}}`, what servers document and
 * what `extensions_config.json` stores) and a bare name-to-config map are
 * accepted, so a copied snippet works either way.
 *
 * Only the shape needed to merge the entry into the config map is checked
 * here; transport, command allowlist, and argument screening are enforced by
 * the Gateway, which is the boundary that has to hold regardless of client.
 */
export function parseMCPServerDefinition(
  input: string,
): Record<string, MCPServerConfig> {
  const trimmed = input.trim();
  if (!trimmed) {
    throw new MCPServerDefinitionError("Paste an MCP server definition.");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch (error) {
    throw new MCPServerDefinitionError(
      error instanceof Error ? error.message : "Invalid JSON.",
    );
  }

  if (!isPlainObject(parsed)) {
    throw new MCPServerDefinitionError(
      "Expected a JSON object describing one or more MCP servers.",
    );
  }

  const wrapped = parsed.mcpServers;
  const servers = wrapped === undefined ? parsed : wrapped;
  if (!isPlainObject(servers)) {
    throw new MCPServerDefinitionError(
      "Expected `mcpServers` to be an object keyed by server name.",
    );
  }

  const entries = Object.entries(servers);
  if (entries.length === 0) {
    throw new MCPServerDefinitionError(
      "No MCP server found in the definition.",
    );
  }

  return Object.fromEntries(
    entries.map(([name, config]) => {
      if (!name.trim()) {
        throw new MCPServerDefinitionError("Server names cannot be empty.");
      }
      if (!isPlainObject(config)) {
        throw new MCPServerDefinitionError(
          `Server "${name}" must be a JSON object.`,
        );
      }
      // Servers are enabled on add: a definition the operator just pasted is
      // one they want running, and an entry that silently lands disabled reads
      // as a failed add. An explicit `enabled` in the snippet still wins.
      return [
        name,
        {
          enabled: true,
          description: "",
          ...config,
        } as MCPServerConfig,
      ] as const;
    }),
  );
}
