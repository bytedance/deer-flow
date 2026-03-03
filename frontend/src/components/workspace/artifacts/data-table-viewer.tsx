import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  CopyIcon,
  DownloadIcon,
  SearchIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  Artifact,
  ArtifactAction,
  ArtifactActions,
  ArtifactContent,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { useArtifacts } from "./context";

type RowData = Record<string, unknown>;

function formatCellValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function dataToCSV(columns: string[], rows: RowData[]): string {
  const escape = (v: string) =>
    v.includes(",") || v.includes('"') || v.includes("\n")
      ? `"${v.replace(/"/g, '""')}"`
      : v;
  const header = columns.map(escape).join(",");
  const body = rows
    .map((row) => columns.map((col) => escape(formatCellValue(row[col]))).join(","))
    .join("\n");
  return `${header}\n${body}`;
}

export function DataTableViewer({
  className,
  toolName,
  data,
  meta,
}: {
  className?: string;
  toolName: string;
  data: RowData[];
  meta?: {
    count: number;
    total?: number;
    page?: number;
    totalPages?: number;
    warning?: string;
    error?: string;
  };
}) {
  const { t } = useI18n();
  const { setOpen } = useArtifacts();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");

  const columns = useMemo<ColumnDef<RowData>[]>(() => {
    if (data.length === 0) return [];
    const keys = Object.keys(data[0]!);
    return keys.map((key) => ({
      accessorKey: key,
      header: key,
      cell: ({ getValue }) => formatCellValue(getValue()),
      filterFn: "includesString" as const,
    }));
  }, [data]);

  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    globalFilterFn: "includesString",
  });

  const handleCopyCSV = useCallback(async () => {
    const keys = data.length > 0 ? Object.keys(data[0]!) : [];
    const csv = dataToCSV(keys, data);
    try {
      await navigator.clipboard.writeText(csv);
      toast.success(t.clipboard.copiedToClipboard);
    } catch {
      toast.error(t.clipboard.failedToCopyToClipboard);
    }
  }, [data, t]);

  const handleDownloadCSV = useCallback(() => {
    const keys = data.length > 0 ? Object.keys(data[0]!) : [];
    const csv = dataToCSV(keys, data);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${toolName}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [data, toolName]);

  const displayName = toolName.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

  return (
    <Artifact className={cn(className)}>
      <ArtifactHeader className="px-2">
        <div className="flex items-center gap-2">
          <ArtifactTitle>
            <div className="px-2">{displayName}</div>
          </ArtifactTitle>
          {meta && (
            <div className="text-muted-foreground flex items-center gap-1.5 text-xs">
              <span>{t.toolCalls.mcpDataResults(meta.count, meta.total)}</span>
              {meta.page != null &&
                meta.totalPages != null &&
                meta.totalPages > 1 && (
                  <span>
                    {t.toolCalls.mcpDataPage(meta.page, meta.totalPages)}
                  </span>
                )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ArtifactActions>
            <ArtifactAction
              icon={CopyIcon}
              label="Copy as CSV"
              tooltip="Copy as CSV"
              onClick={handleCopyCSV}
            />
            <ArtifactAction
              icon={DownloadIcon}
              label="Download CSV"
              tooltip="Download CSV"
              onClick={handleDownloadCSV}
            />
            <ArtifactAction
              icon={XIcon}
              label={t.common.close}
              onClick={() => setOpen(false)}
              tooltip={t.common.close}
            />
          </ArtifactActions>
        </div>
      </ArtifactHeader>

      <div className="border-b px-3 py-2">
        <div className="relative">
          <SearchIcon className="text-muted-foreground absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
          <input
            className="bg-muted/50 text-foreground placeholder:text-muted-foreground w-full rounded-md border py-1.5 pr-8 pl-8 text-sm outline-none focus:ring-1 focus:ring-ring"
            placeholder="Search all columns..."
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
          />
          {globalFilter && (
            <button
              className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2"
              onClick={() => setGlobalFilter("")}
              type="button"
            >
              <XIcon className="size-3.5" />
            </button>
          )}
        </div>
      </div>

      {meta?.warning && (
        <div className="border-b bg-amber-50 px-3 py-1.5 text-xs text-amber-800 dark:bg-amber-900/20 dark:text-amber-400">
          {meta.warning}
        </div>
      )}
      {meta?.error && (
        <div className="border-b bg-red-50 px-3 py-1.5 text-xs text-red-800 dark:bg-red-900/20 dark:text-red-400">
          {meta.error}
        </div>
      )}

      <ArtifactContent className="p-0">
        <div className="size-full overflow-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="bg-muted/50 sticky top-0 z-10">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th
                      key={header.id}
                      className={cn(
                        "text-muted-foreground border-b px-3 py-2 text-left text-xs font-medium whitespace-nowrap",
                        header.column.getCanSort() &&
                          "cursor-pointer select-none hover:text-foreground",
                      )}
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      <div className="flex items-center gap-1">
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                        {header.column.getIsSorted() === "asc" ? (
                          <ArrowUpIcon className="size-3" />
                        ) : header.column.getIsSorted() === "desc" ? (
                          <ArrowDownIcon className="size-3" />
                        ) : header.column.getCanSort() ? (
                          <ArrowUpDownIcon className="size-3 opacity-30" />
                        ) : null}
                      </div>
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className="hover:bg-muted/30 transition-colors"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className="max-w-[20rem] truncate border-b px-3 py-1.5 whitespace-nowrap"
                      title={formatCellValue(cell.getValue())}
                    >
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </td>
                  ))}
                </tr>
              ))}
              {table.getRowModel().rows.length === 0 && (
                <tr>
                  <td
                    colSpan={columns.length}
                    className="text-muted-foreground py-8 text-center"
                  >
                    {globalFilter ? "No matching records" : "No data"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="text-muted-foreground border-t px-3 py-2 text-xs">
          {table.getFilteredRowModel().rows.length} of {data.length} row
          {data.length === 1 ? "" : "s"}
          {globalFilter && " (filtered)"}
        </div>
      </ArtifactContent>
    </Artifact>
  );
}
