// ─── Types ───────────────────────────────────────────────────

export interface McpToolMeta {
  count: number;
  total?: number;
  page?: number;
  totalPages?: number;
  warning?: string;
  error?: string;
}

// ─── Result Detection ────────────────────────────────────────

/**
 * Shape-based detection: any MCP server returning `{ data: [...] }` matches.
 */
export function isMcpDataResult(
  result: string | Record<string, unknown> | undefined,
): result is Record<string, unknown> {
  if (!result || typeof result === "string") return false;
  if (Array.isArray(result.data)) return true;
  return false;
}

// ─── Meta Shape Extractors (keyed by server prefix) ──────────

type MetaExtractor = (result: Record<string, unknown>) => McpToolMeta;

function extractFiscalMeta(result: Record<string, unknown>): McpToolMeta {
  const data = result.data as unknown[];
  const count = data.length;
  const meta = result.meta as Record<string, unknown> | undefined;
  return {
    count,
    total:
      typeof meta?.["total-count"] === "number"
        ? meta["total-count"]
        : undefined,
    page:
      typeof meta?.["page-number"] === "number"
        ? meta["page-number"]
        : undefined,
    totalPages:
      typeof meta?.["total-pages"] === "number"
        ? meta["total-pages"]
        : undefined,
    warning: typeof result.warning === "string" ? result.warning : undefined,
    error: typeof result.error === "string" ? result.error : undefined,
  };
}

function extractWorldbankMeta(result: Record<string, unknown>): McpToolMeta {
  const data = result.data as unknown[];
  const count = data.length;
  const pagination = result.pagination as Record<string, unknown> | undefined;
  return {
    count,
    total:
      typeof pagination?.total === "number" ? pagination.total : undefined,
    page: typeof pagination?.page === "number" ? pagination.page : undefined,
    totalPages:
      typeof pagination?.pages === "number" ? pagination.pages : undefined,
    warning: typeof result.warning === "string" ? result.warning : undefined,
    error: typeof result.error === "string" ? result.error : undefined,
  };
}

const META_EXTRACTORS: Record<string, MetaExtractor> = {
  fiscaldata_: extractFiscalMeta,
  worldbank_: extractWorldbankMeta,
};

/**
 * Finds the right extractor by tool name prefix, falls back to generic.
 */
export function extractMcpMeta(
  toolName: string,
  result: Record<string, unknown>,
): McpToolMeta {
  for (const [prefix, extractor] of Object.entries(META_EXTRACTORS)) {
    if (toolName.startsWith(prefix)) {
      return extractor(result);
    }
  }
  // Generic fallback: just count the data array
  const data = result.data as unknown[];
  return { count: data.length };
}

// ─── Tool Label Descriptors (keyed by exact tool name) ───────

type ToolDescriptor = (args: Record<string, unknown>) => string;

function withArgs(
  label: string,
  args: Record<string, unknown>,
  keys: string[],
): string {
  const s = (v: unknown): string =>
    typeof v === "string" ? v : JSON.stringify(v);
  const parts: string[] = [];
  for (const key of keys) {
    if (args[key] != null) {
      parts.push(`${key}: ${s(args[key])}`);
    }
  }
  if (parts.length === 0) return label;
  return `${label} (${parts.join(", ")})`;
}

function autoLabel(name: string): string {
  return name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

const TOOL_DESCRIPTORS: Record<string, ToolDescriptor> = {
  fiscaldata_get_national_debt: (a) =>
    withArgs("Query national debt", a, ["start_date", "end_date"]),
  fiscaldata_get_treasury_rates: (a) =>
    withArgs("Query treasury rates", a, ["start_date", "end_date"]),
  worldbank_get_indicator_data: (a) =>
    withArgs("Get indicator", a, ["indicator_code", "country_codes"]),
  worldbank_list_countries: (a) =>
    withArgs("List countries", a, ["region"]),
  worldbank_list_indicators: (a) =>
    withArgs("List indicators", a, ["search"]),
};

/**
 * Returns a custom label if the tool is registered, otherwise auto-generates
 * a human-readable label from the tool name.
 */
export function describeMcpTool(
  name: string,
  args: Record<string, unknown>,
  fallback: string,
): string {
  const descriptor = TOOL_DESCRIPTORS[name];
  if (descriptor) return descriptor(args);
  // Auto-generate for any MCP-prefixed tool not in the registry
  for (const prefix of Object.keys(META_EXTRACTORS)) {
    if (name.startsWith(prefix)) return autoLabel(name);
  }
  return fallback;
}
