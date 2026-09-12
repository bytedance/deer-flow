import type { MCPServerConfig } from "./types";

export type MCPServerDefinitionErrorCode =
  | "emptyDefinition"
  | "invalidJson"
  | "rootNotObject"
  | "emptyServerMap"
  | "serverConfigNotObject";

/** A pasted definition that is not a usable `mcpServers` map. */
export class MCPServerDefinitionError extends Error {
  readonly code: MCPServerDefinitionErrorCode;
  readonly serverName?: string;

  constructor(code: MCPServerDefinitionErrorCode, serverName?: string) {
    super(code);
    this.name = "MCPServerDefinitionError";
    this.code = code;
    this.serverName = serverName;
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isWrappedServerMap(value: Record<string, unknown>): value is Record<
  string,
  unknown
> & {
  mcpServers: Record<string, unknown>;
} {
  if (!Object.hasOwn(value, "mcpServers") || !isPlainObject(value.mcpServers)) {
    return false;
  }
  const candidates = Object.values(value.mcpServers);
  return candidates.length === 0 || candidates.every(isPlainObject);
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
    throw new MCPServerDefinitionError("emptyDefinition");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new MCPServerDefinitionError("invalidJson");
  }

  if (!isPlainObject(parsed)) {
    throw new MCPServerDefinitionError("rootNotObject");
  }

  // A bare server is allowed to be named `mcpServers`. Treat that key as the
  // wrapper only when its value itself looks like a name-to-config map.
  const servers = isWrappedServerMap(parsed) ? parsed.mcpServers : parsed;

  const entries = Object.entries(servers);
  if (entries.length === 0) {
    throw new MCPServerDefinitionError("emptyServerMap");
  }

  return Object.fromEntries(
    entries.map(([name, config]) => {
      if (!isPlainObject(config)) {
        throw new MCPServerDefinitionError("serverConfigNotObject", name);
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
