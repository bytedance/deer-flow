"use client";

import { CheckIcon, CopyIcon, DownloadIcon } from "lucide-react";
import {
  type HTMLAttributes,
  type ReactElement,
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
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

type ReactElementWithProps = ReactElement & {
  props: { children?: React.ReactNode; className?: string };
};

function isReactElement(node: React.ReactNode): node is ReactElementWithProps {
  return node != null && typeof node === "object" && "props" in node;
}

/** Extract plain-text rows from a <table>'s React children (thead + tbody). */
function extractTableData(children: React.ReactNode): {
  headers: string[];
  rows: string[][];
} {
  const headers: string[] = [];
  const rows: string[][] = [];

  const toText = (node: React.ReactNode): string => {
    if (node == null) return "";
    if (typeof node === "string" || typeof node === "number") return String(node);
    if (Array.isArray(node)) return node.map(toText).join("");
    if (isReactElement(node)) return toText(node.props.children);
    return "";
  };

  const processRows = (
    section: React.ReactNode,
    target: "head" | "body",
  ) => {
    if (!isReactElement(section)) return;
    const sectionChildren = Array.isArray(section.props.children)
      ? section.props.children
      : [section.props.children];

    for (const row of sectionChildren) {
      if (!isReactElement(row)) continue;
      const cells = Array.isArray(row.props.children)
        ? row.props.children
        : [row.props.children];
      const values = (cells as React.ReactNode[]).map(toText);
      if (target === "head") {
        headers.push(...values);
      } else {
        rows.push(values);
      }
    }
  };

  const kids = Array.isArray(children) ? children : [children];
  for (const child of kids) {
    if (!isReactElement(child)) continue;
    const tag = typeof child.type === "string" ? child.type : "";
    if (tag === "thead") processRows(child, "head");
    else if (tag === "tbody") processRows(child, "body");
  }

  return { headers, rows };
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

  const getTableData = useCallback(() => {
    return extractTableData(props.children);
  }, [props.children]);

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
