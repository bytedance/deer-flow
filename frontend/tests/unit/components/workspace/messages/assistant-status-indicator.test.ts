import { describe, expect, it } from "vitest";

const mockT = {
  statusIndicators: {
    thinking: "Thinking…",
    queryingData: "Querying data…",
    generatingReport: "Generating report…",
    analyzing: "Analyzing…",
  },
} as const;

function deriveStatusText(toolNames: string[], t: typeof mockT): string {
  const DATA_TOOLS = new Set([
    "web_search",
    "web_fetch",
    "image_search",
    "http_connector",
    "search_knowledge_base",
  ]);
  const REPORT_TOOLS = new Set([
    "report_template_prepare_run",
    "report_template_render_step",
    "report_template_run_data_steps",
    "report_template_render_report",
    "report_template_export",
    "present_files",
  ]);
  const ANALYSIS_TOOLS = new Set(["bash", "read_file", "write_file", "str_replace"]);

  if (toolNames.length === 0) return t.statusIndicators.thinking;
  const lastTool = toolNames[toolNames.length - 1] ?? "";
  if (DATA_TOOLS.has(lastTool)) return t.statusIndicators.queryingData;
  if (REPORT_TOOLS.has(lastTool)) return t.statusIndicators.generatingReport;
  if (ANALYSIS_TOOLS.has(lastTool)) return t.statusIndicators.analyzing;
  return t.statusIndicators.thinking;
}

describe("deriveStatusText", () => {
  it("returns thinking for empty tool list", () => {
    expect(deriveStatusText([], mockT)).toBe("Thinking…");
  });

  it("returns queryingData for web_search", () => {
    expect(deriveStatusText(["web_search"], mockT)).toBe("Querying data…");
  });

  it("returns queryingData for http_connector", () => {
    expect(deriveStatusText(["http_connector"], mockT)).toBe("Querying data…");
  });

  it("returns generatingReport for report_template_render_report", () => {
    expect(deriveStatusText(["report_template_render_report"], mockT)).toBe("Generating report…");
  });

  it("returns analyzing for bash", () => {
    expect(deriveStatusText(["bash"], mockT)).toBe("Analyzing…");
  });

  it("uses last tool when multiple tools are active", () => {
    expect(deriveStatusText(["web_search", "bash", "report_template_export"], mockT)).toBe("Generating report…");
  });

  it("returns thinking for unknown tools", () => {
    expect(deriveStatusText(["some_custom_tool"], mockT)).toBe("Thinking…");
  });
});
