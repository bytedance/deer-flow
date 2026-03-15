"use client";

import { CheckIcon, CopyIcon, DownloadIcon, Maximize2Icon } from "lucide-react";
import {
  type HTMLAttributes,
  useCallback,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTableViewer } from "@/components/workspace/table-viewer-context";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

/** Extract plain-text rows and link hrefs from the rendered <table> DOM element. */
function extractTableDataFromDOM(table: HTMLTableElement): {
  headers: string[];
  rows: string[][];
  links: (string | undefined)[][];
} {
  const headers = Array.from(
    table.querySelectorAll("thead th, thead td"),
  ).map((cell) => cell.textContent?.trim() ?? "");

  const rows: string[][] = [];
  const links: (string | undefined)[][] = [];

  for (const row of table.querySelectorAll("tbody tr")) {
    const rowTexts: string[] = [];
    const rowLinks: (string | undefined)[] = [];
    for (const cell of row.querySelectorAll("td, th")) {
      rowTexts.push(cell.textContent?.trim() ?? "");
      const anchor = cell.querySelector("a[href]");
      rowLinks.push(
        anchor ? (anchor as HTMLAnchorElement).href : undefined,
      );
    }
    rows.push(rowTexts);
    links.push(rowLinks);
  }

  return { headers, rows, links };
}

function toCsv(headers: string[], rows: string[][]): string {
  const escape = (v: string) =>
    v.includes(",") || v.includes('"') || v.includes("\n")
      ? `"${v.replace(/"/g, '""')}"`
      : v;
  const headerLine = headers.map(escape).join(",");
  const bodyLines = rows.map((r) => r.map(escape).join(",")).join("\n");
  return `${headerLine}\n${bodyLines}`;
}

export function ScrollableTable(props: HTMLAttributes<HTMLTableElement>) {
  const { t } = useI18n();
  const [isCopied, setIsCopied] = useState(false);
  const tableRef = useRef<HTMLTableElement>(null);
  const { openTable } = useTableViewer();

  const getTableData = useCallback(() => {
    if (!tableRef.current)
      return { headers: [] as string[], rows: [] as string[][], links: [] as (string | undefined)[][] };
    return extractTableDataFromDOM(tableRef.current);
  }, []);

  const handleCopy = useCallback(async () => {
    const { headers, rows } = getTableData();
    const csv = toCsv(headers, rows);
    try {
      await navigator.clipboard.writeText(csv);
      setIsCopied(true);
      toast.success(t.clipboard.copiedToClipboard);
      setTimeout(() => setIsCopied(false), 2000);
    } catch {
      toast.error(t.clipboard.failedToCopyToClipboard);
    }
  }, [getTableData, t]);

  const handleDownload = useCallback(() => {
    const { headers, rows } = getTableData();
    const csv = toCsv(headers, rows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "table.csv";
    a.click();
    URL.revokeObjectURL(url);
  }, [getTableData]);

  const handleOpen = useCallback(() => {
    const { headers, rows, links } = getTableData();
    openTable({ headers, rows, links, title: "Table" });
  }, [getTableData, openTable]);

  const CopyIconEl = isCopied ? CheckIcon : CopyIcon;

  return (
    <div className="group/table my-2 overflow-hidden rounded-md border">
      <div className="flex items-center justify-end gap-0.5 border-b bg-muted/30 px-2 py-0.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="size-6 text-muted-foreground hover:text-foreground"
              onClick={handleOpen}
            >
              <Maximize2Icon className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top" className="text-xs">
            Open in side panel
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="size-6 text-muted-foreground hover:text-foreground"
              onClick={handleCopy}
            >
              <CopyIconEl className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top" className="text-xs">
            Copy as CSV
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="size-6 text-muted-foreground hover:text-foreground"
              onClick={handleDownload}
            >
              <DownloadIcon className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top" className="text-xs">
            Download CSV
          </TooltipContent>
        </Tooltip>
      </div>
      <div className="max-h-96 overflow-auto">
        <table
          {...props}
          ref={tableRef}
          className={cn(
            "w-full border-collapse text-sm",
            "[&_th]:bg-muted/50 [&_th]:px-3 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-medium [&_th]:whitespace-nowrap",
            "[&_td]:px-3 [&_td]:py-1.5 [&_td]:whitespace-nowrap",
            "[&_tr]:border-b [&_tr:last-child]:border-0",
            "[&_thead]:sticky [&_thead]:top-0 [&_thead]:z-10 [&_thead]:bg-muted/50",
            props.className,
          )}
        />
      </div>
    </div>
  );
}
