"use client";

import { Loader2Icon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

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

const ANALYSIS_TOOLS = new Set([
  "bash",
  "read_file",
  "write_file",
  "str_replace",
]);

export function deriveStatusText(
  toolNames: string[],
  t: ReturnType<typeof useI18n>["t"],
): string {
  if (toolNames.length === 0) return t.statusIndicators.thinking;

  const lastTool = toolNames[toolNames.length - 1] ?? "";

  if (DATA_TOOLS.has(lastTool)) return t.statusIndicators.queryingData;
  if (REPORT_TOOLS.has(lastTool)) return t.statusIndicators.generatingReport;
  if (ANALYSIS_TOOLS.has(lastTool)) return t.statusIndicators.analyzing;

  return t.statusIndicators.thinking;
}

export function AssistantStatusIndicator({
  toolNames,
  className,
}: {
  toolNames: string[];
  className?: string;
}) {
  const { t } = useI18n();
  const statusText = deriveStatusText(toolNames, t);

  return (
    <div className={cn("flex items-center gap-2 py-2", className)}>
      <Loader2Icon className="text-muted-foreground size-4 animate-spin" />
      <span className="text-muted-foreground text-sm">{statusText}</span>
    </div>
  );
}
