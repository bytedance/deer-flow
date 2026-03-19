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

export interface ToolSearchEntry {
  name: string;
  description: string;
  parameters: string[];
  server?: string | null;
}

export interface ToolSearchResult {
  found: number;
  query?: string;
  tools: ToolSearchEntry[];
  message?: string;
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

/**
 * Shape-based detection for tool_search results.
 * Returns an intersection so the predicate satisfies TypeScript's assignability
 * requirement while still exposing all ToolSearchResult fields.
 */
export function isToolSearchResult(
  result: string | Record<string, unknown> | undefined,
): result is ToolSearchResult & Record<string, unknown> {
  if (!result || typeof result === "string") return false;
  return typeof result.found === "number" && Array.isArray(result.tools);
}

// ─── Result Normalization (non-standard → {data: [...]}) ─────
//
// Some MCP servers return `{ studies: [...] }` or `{ records: [...] }` instead
// of the standard `{ data: [...] }` shape. `normalizeMcpResult` maps each
// known tool's native data field to `data` so `McpDataToolCall` can render
// it without modification.

type DataExtractor =
  | string
  | ((r: Record<string, unknown>) => unknown[] | undefined);

const DATA_EXTRACTORS: Record<string, DataExtractor> = {
  // ClinicalTrials.gov
  clinicaltrials_search_studies: "studies",
  // NCBI E-utilities
  ncbi_summary: "records",
  ncbi_link: "linksets",
  ncbi_global_search: "results",
  ncbi_citmatch: "matches",
  ncbi_search: (r) =>
    Array.isArray(r.ids)
      ? (r.ids as string[]).map((id) => ({ id }))
      : undefined,
  ncbi_info: (r) => {
    if (Array.isArray(r.databases)) return r.databases as unknown[];
    if (Array.isArray(r.fields)) return r.fields as unknown[];
    return undefined;
  },
};

/**
 * Normalizes a tool result to the `{ data: [...] }` shape expected by
 * `McpDataToolCall`. Tools already in standard form are returned unchanged.
 */
export function normalizeMcpResult(
  toolName: string,
  result: Record<string, unknown>,
): Record<string, unknown> {
  if (Array.isArray(result.data)) return result;
  const extractor = DATA_EXTRACTORS[toolName];
  if (!extractor) return result;
  const data =
    typeof extractor === "string"
      ? (result[extractor] as unknown[] | undefined)
      : extractor(result);
  if (!Array.isArray(data)) return result;
  return { ...result, data };
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

function extractClinicalTrialsMeta(result: Record<string, unknown>): McpToolMeta {
  const data = result.data as unknown[];
  return {
    count: data.length,
    total:
      typeof result.totalCount === "number" ? result.totalCount : undefined,
    warning: typeof result.warning === "string" ? result.warning : undefined,
    error: typeof result.error === "string" ? result.error : undefined,
  };
}

function extractNcbiMeta(result: Record<string, unknown>): McpToolMeta {
  const data = result.data as unknown[];
  return {
    count: data.length,
    // ncbi_search exposes `count` as the total across all pages
    total: typeof result.count === "number" ? result.count : undefined,
    warning: typeof result.warning === "string" ? result.warning : undefined,
    error: typeof result.error === "string" ? result.error : undefined,
  };
}

const META_EXTRACTORS: Record<string, MetaExtractor> = {
  clinicaltrials_: extractClinicalTrialsMeta,
  fiscaldata_: extractFiscalMeta,
  ncbi_: extractNcbiMeta,
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

  // ── ClinicalTrials MCP ─────────────────────────────────────
  clinicaltrials_search_studies: (a) =>
    withArgs("Searching ClinicalTrials.gov", a, ["query", "condition", "intervention"]),
  clinicaltrials_get_study: (a) =>
    withArgs("Getting study details", a, ["nct_id"]),
  clinicaltrials_get_stats: () => "Getting clinical trial statistics",

  // ── NCBI MCP ───────────────────────────────────────────────
  ncbi_search: (a) =>
    withArgs("Searching NCBI", a, ["term", "db"]),
  ncbi_summary: (a) =>
    withArgs("Getting NCBI summaries", a, ["db"]),
  ncbi_fetch: (a) =>
    withArgs("Fetching NCBI records", a, ["db"]),
  ncbi_link: (a) =>
    withArgs("Finding linked records", a, ["dbfrom"]),
  ncbi_info: (a) =>
    withArgs("Getting NCBI database info", a, ["db"]),
  ncbi_global_search: (a) =>
    withArgs("Global NCBI search", a, ["term"]),
  ncbi_spell: (a) =>
    withArgs("Checking spelling", a, ["term"]),
  ncbi_citmatch: (a) =>
    withArgs("Matching citation", a, ["title"]),

  // ── Built-in: Tool Search ───────────────────────────────────
  tool_search: (a) =>
    withArgs("Searching for tools", a, ["query"]),
};

// ─── Server Prefix Labels (Tier 2 fallback) ──────────────────

/**
 * Known MCP server prefixes for auto-generating labels from tool names
 * that aren't in TOOL_DESCRIPTORS. The prefix is stripped and the
 * remaining name is humanized.
 */
const SERVER_PREFIXES: string[] = [
  "clinicaltrials_",
  "firecrawl_",
  "fiscaldata_",
  "ncbi_",
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
  // Structured data tools (MCP servers returning {data: [...]})
  if (
    name.startsWith("worldbank_") ||
    name.startsWith("fiscaldata_") ||
    name.startsWith("clinicaltrials_") ||
    name.startsWith("ncbi_")
  ) {
    return "database";
  }
  return "default";
}
