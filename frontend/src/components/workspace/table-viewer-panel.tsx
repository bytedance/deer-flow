"use client";

import {
  CheckIcon,
  CopyIcon,
  DownloadIcon,
  SearchIcon,
  WrapTextIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { DataGrid, type Column, type SortColumn } from "react-data-grid";
import "react-data-grid/lib/styles.css";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { useTableViewer } from "./table-viewer-context";

type RowRecord = Record<string, string>;

function toCsv(headers: string[], rows: string[][]): string {
  const escape = (v: string) =>
    v.includes(",") || v.includes('"') || v.includes("\n")
      ? `"${v.replace(/"/g, '""')}"`
      : v;
  const headerLine = headers.map(escape).join(",");
  const bodyLines = rows.map((r) => r.map(escape).join(",")).join("\n");
  return `${headerLine}\n${bodyLines}`;
}

export function TableViewerPanel({ className }: { className?: string }) {
  const { t } = useI18n();
  const { tableData, closeTable } = useTableViewer();
  const [sortColumns, setSortColumns] = useState<readonly SortColumn[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [isCopied, setIsCopied] = useState(false);
  const [wrapText, setWrapText] = useState(false);

  const { headers, rows, links, title } = tableData ?? {
    headers: [],
    rows: [],
    links: undefined,
    title: undefined,
  };

  // Build columns: row number + data columns
  const columns = useMemo<readonly Column<RowRecord>[]>(() => {
    const rowNumCol: Column<RowRecord> = {
      key: "__row_num__",
      name: "",
      frozen: true,
      resizable: false,
      sortable: false,
      width: 50,
      minWidth: 40,
      cellClass: "rdg-row-num",
      headerCellClass: "rdg-row-num-header",
      renderCell: ({ rowIdx }) => <span>{rowIdx + 1}</span>,
    };

    const dataCols: Column<RowRecord>[] = headers.map((h) => ({
      key: h,
      name: h,
      resizable: true,
      sortable: true,
      minWidth: 80,
      ...(wrapText ? { maxWidth: 320 } : {}),
      renderCell: ({ row }: { row: RowRecord }) => {
        const linkKey = `__link__${h}`;
        const href = row[linkKey];
        const text = row[h] ?? "";
        if (href) {
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline decoration-primary/40 hover:decoration-primary"
              title={text}
            >
              {text}
            </a>
          );
        }
        return <span title={text}>{text}</span>;
      },
    }));

    return [rowNumCol, ...dataCols];
  }, [headers, wrapText]);

  // Build row data from string arrays, including link hrefs as __link__<header> keys
  const allRows = useMemo<RowRecord[]>(
    () =>
      rows.map((r, rowIdx) => {
        const record: RowRecord = {};
        headers.forEach((h, colIdx) => {
          record[h] = r[colIdx] ?? "";
          const href = links?.[rowIdx]?.[colIdx];
          if (href) record[`__link__${h}`] = href;
        });
        return record;
      }),
    [rows, headers, links],
  );

  // Filter rows by search query
  const filteredRows = useMemo(() => {
    if (!searchQuery) return allRows;
    const q = searchQuery.toLowerCase();
    return allRows.filter((row) =>
      Object.values(row).some((v) => v.toLowerCase().includes(q)),
    );
  }, [allRows, searchQuery]);

  // Sort rows
  const sortedRows = useMemo(() => {
    if (sortColumns.length === 0) return filteredRows;

    return [...filteredRows].sort((a, b) => {
      for (const { columnKey, direction } of sortColumns) {
        const aVal = a[columnKey] ?? "";
        const bVal = b[columnKey] ?? "";
        // Try numeric comparison first
        const aNum = Number(aVal);
        const bNum = Number(bVal);
        let cmp: number;
        if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) {
          cmp = aNum - bNum;
        } else {
          cmp = aVal.localeCompare(bVal);
        }
        if (cmp !== 0) return direction === "ASC" ? cmp : -cmp;
      }
      return 0;
    });
  }, [filteredRows, sortColumns]);

  const handleCopy = useCallback(async () => {
    const csv = toCsv(headers, rows);
    try {
      await navigator.clipboard.writeText(csv);
      setIsCopied(true);
      toast.success(t.clipboard.copiedToClipboard);
      setTimeout(() => setIsCopied(false), 2000);
    } catch {
      toast.error(t.clipboard.failedToCopyToClipboard);
    }
  }, [headers, rows, t]);

  const handleDownload = useCallback(() => {
    const csv = toCsv(headers, rows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title ?? "table"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [headers, rows, title]);

  const CopyIconEl = isCopied ? CheckIcon : CopyIcon;

  return (
    <div
      className={cn(
        "table-viewer-panel flex h-full flex-col overflow-hidden rounded-lg border bg-background shadow-sm",
        className,
      )}
    >
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b bg-muted/30 px-3 py-2">
        <span className="truncate text-sm font-medium">
          {title ?? "Table"}
        </span>
        <div className="flex items-center gap-0.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  "size-7",
                  wrapText
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
                onClick={() => setWrapText((v) => !v)}
              >
                <WrapTextIcon className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">
              {wrapText ? "Disable text wrap" : "Enable text wrap"}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="size-7 text-muted-foreground hover:text-foreground"
                onClick={handleCopy}
              >
                <CopyIconEl className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">
              Copy as CSV
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="size-7 text-muted-foreground hover:text-foreground"
                onClick={handleDownload}
              >
                <DownloadIcon className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">
              Download CSV
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="size-7 text-muted-foreground hover:text-foreground"
                onClick={closeTable}
              >
                <XIcon className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">
              {t.common.close}
            </TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* Search */}
      <div className="shrink-0 border-b px-3 py-2">
        <div className="relative">
          <SearchIcon className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            className="w-full rounded-md border bg-muted/50 py-1.5 pr-8 pl-8 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
            placeholder="Search all columns..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setSearchQuery("")}
              type="button"
            >
              <XIcon className="size-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Data Grid */}
      <div className={cn("min-h-0 grow", wrapText && "rdg-wrap")}>
        <DataGrid
          className="h-full"
          columns={columns}
          rows={sortedRows}
          sortColumns={sortColumns}
          onSortColumnsChange={setSortColumns}
          defaultColumnOptions={{ resizable: true, sortable: true }}
          rowHeight={35}
          headerRowHeight={35}
          enableVirtualization={!wrapText}
        />
      </div>

      {/* Footer */}
      <div className="shrink-0 border-t px-3 py-1.5 text-xs text-muted-foreground">
        {sortedRows.length}
        {searchQuery ? ` of ${rows.length}` : ""} row
        {rows.length === 1 ? "" : "s"}
        {searchQuery && " (filtered)"}
        {headers.length > 0 &&
          ` · ${headers.length} column${headers.length === 1 ? "" : "s"}`}
      </div>
    </div>
  );
}
