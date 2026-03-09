// ─── Tool Display Categories ─────────────────────────────────
//
// Maps tool names to unified display styles. Tools in the same category
// render identically in the UI. To add a new web-search or web-fetch tool,
// simply add its name to the appropriate set below.

export type ToolDisplayCategory = "web_search" | "web_fetch";

const WEB_SEARCH_TOOLS: ReadonlySet<string> = new Set([
  "web_search",
  "firecrawl_search",
]);

const WEB_FETCH_TOOLS: ReadonlySet<string> = new Set([
  "web_fetch",
  "firecrawl_scrape",
]);

/**
 * Returns the unified display category for a tool, or `undefined` if
 * the tool doesn't belong to any category.
 */
export function getToolDisplayCategory(
  name: string,
): ToolDisplayCategory | undefined {
  if (WEB_SEARCH_TOOLS.has(name)) return "web_search";
  if (WEB_FETCH_TOOLS.has(name)) return "web_fetch";
  return undefined;
}

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
  // ── Fiscal Data MCP ────────────────────────────────────────
  fiscaldata_get_national_debt: (a) =>
    withArgs("Querying national debt", a, ["start_date", "end_date"]),
  fiscaldata_get_interest_rates: (a) =>
    withArgs("Querying interest rates", a, ["start_date", "end_date"]),
  fiscaldata_get_exchange_rates: (a) =>
    withArgs("Querying exchange rates", a, ["country", "currency"]),
  fiscaldata_get_interest_expense: (a) =>
    withArgs("Querying interest expense", a, ["start_date", "end_date"]),
  fiscaldata_get_treasury_statement: (a) =>
    withArgs("Querying treasury statement", a, ["table"]),
  fiscaldata_query_dataset: (a) =>
    withArgs("Querying fiscal dataset", a, ["endpoint"]),

  // ── World Bank MCP ─────────────────────────────────────────
  worldbank_get_indicator_data: (a) =>
    withArgs("Fetching indicator data", a, ["indicator_code", "country_codes"]),
  worldbank_list_countries: (a) =>
    withArgs("Listing countries", a, ["region"]),
  worldbank_search_indicators: (a) =>
    withArgs("Searching indicators", a, ["query"]),

  // ── PostgreSQL MCP (postgres-mcp) ──────────────────────────
  list_schemas: () => "Listing database schemas",
  list_objects: (a) =>
    withArgs("Listing database objects", a, ["schema"]),
  get_object_details: (a) =>
    withArgs("Inspecting table structure", a, ["object_name"]),
  execute_sql: () => "Executing SQL query",
  explain_query: () => "Analyzing query plan",
  get_top_queries: () => "Finding slowest queries",
  analyze_workload_indexes: () => "Analyzing workload indexes",
  analyze_query_indexes: () => "Analyzing query indexes",
  analyze_db_health: () => "Checking database health",

  // ── Alpha Vantage MCP (av-mcp) ─────────────────────────────
  TOOL_LIST: () => "Listing available financial data tools",
  TOOL_GET: (a) =>
    withArgs("Getting tool details", a, ["tool_name"]),
  TOOL_CALL: (a) =>
    withArgs("Fetching financial data", a, ["tool_name"]),

  // ── Firecrawl MCP ──────────────────────────────────────────
  firecrawl_scrape: (a) =>
    withArgs("Scraping web page", a, ["url"]),
  firecrawl_batch_scrape: () => "Scraping multiple pages",
  firecrawl_crawl: (a) =>
    withArgs("Crawling website", a, ["url"]),
  firecrawl_search: (a) =>
    withArgs("Searching the web", a, ["query"]),
  firecrawl_map: (a) =>
    withArgs("Mapping site URLs", a, ["url"]),
  firecrawl_extract: () => "Extracting structured data",
  firecrawl_agent: () => "Running web research agent",
};

// ─── Server Prefix Labels (Tier 2 fallback) ──────────────────

/**
 * Known MCP server prefixes for auto-generating labels from tool names
 * that aren't in TOOL_DESCRIPTORS. The prefix is stripped and the
 * remaining name is humanized.
 */
const SERVER_PREFIXES: string[] = [
  "firecrawl_",
  "fiscaldata_",
  "worldbank_",
];

/**
 * Returns a custom label if the tool is registered, otherwise auto-generates
 * a human-readable label from the tool name.
 *
 * Resolution order:
 *   1. Exact match in TOOL_DESCRIPTORS
 *   2. Known server prefix → auto-label from remaining name
 *   3. Fallback string
 */
export function describeMcpTool(
  name: string,
  args: Record<string, unknown>,
  fallback: string,
): string {
  // Tier 1: exact match
  const descriptor = TOOL_DESCRIPTORS[name];
  if (descriptor) return descriptor(args);
  // Tier 2: known server prefix → humanize the remainder
  for (const prefix of SERVER_PREFIXES) {
    if (name.startsWith(prefix)) return autoLabel(name);
  }
  // Tier 2b: known meta-extractor prefix (legacy compat)
  for (const prefix of Object.keys(META_EXTRACTORS)) {
    if (name.startsWith(prefix)) return autoLabel(name);
  }
  return fallback;
}

// ─── Icon Hint (for message-group rendering) ─────────────────

export type ToolIconHint = "database" | "globe" | "chart" | "terminal" | "default";

/**
 * Returns a semantic icon hint for a tool name so the UI can pick an
 * appropriate icon without hardcoding tool names in the component.
 */
export function getToolIconHint(name: string): ToolIconHint {
  // Database tools
  if (
    name === "execute_sql" ||
    name === "explain_query" ||
    name === "list_schemas" ||
    name === "list_objects" ||
    name === "get_object_details" ||
    name === "get_top_queries" ||
    name === "analyze_workload_indexes" ||
    name === "analyze_query_indexes" ||
    name === "analyze_db_health"
  ) {
    return "database";
  }
  // Web/scraping tools
  if (name.startsWith("firecrawl_")) return "globe";
  // Financial data tools
  if (name === "TOOL_LIST" || name === "TOOL_GET" || name === "TOOL_CALL") {
    return "chart";
  }
  return "default";
}
