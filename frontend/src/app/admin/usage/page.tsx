"use client";

import { useEffect, useMemo, useState } from "react";

import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";

import { AdminScopeBanner } from "@/components/admin/admin-scope-banner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { getAdminUsage } from "@/core/admin/api";
import type { UsageRecord } from "@/core/admin/types";
import { useI18n } from "@/core/i18n/hooks";

export default function AdminUsagePage() {
  const { t } = useI18n();
  const [records, setRecords] = useState<UsageRecord[]>([]);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sorting, setSorting] = useState<SortingState>([]);

  const refresh = () => {
    getAdminUsage(startDate || undefined, endDate || undefined)
      .then(setRecords)
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const columns = useMemo(
    () => [
      { accessorKey: "timestamp", header: t.admin.timestamp, cell: (info: { getValue: () => string }) => info.getValue().slice(0, 19) },
      { accessorKey: "tenant_id", header: t.admin.tenant },
      { accessorKey: "model_name", header: t.admin.model },
      { accessorKey: "input_tokens", header: t.admin.input, cell: (info: { getValue: () => number }) => info.getValue().toLocaleString() },
      { accessorKey: "output_tokens", header: t.admin.output, cell: (info: { getValue: () => number }) => info.getValue().toLocaleString() },
      { accessorKey: "total_tokens", header: t.admin.total, cell: (info: { getValue: () => number }) => info.getValue().toLocaleString() },
      { accessorKey: "cost_usd", header: t.admin.cost, cell: (info: { getValue: () => number }) => `$${info.getValue().toFixed(6)}` },
    ],
    [t],
  );

  const table = useReactTable({
    data: records,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 20 } },
  });

  const totalCost = records.reduce((sum, r) => sum + r.cost_usd, 0);
  const totalTokens = records.reduce((sum, r) => sum + r.total_tokens, 0);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{t.admin.usageReports}</h1>
      <AdminScopeBanner />

      {error && (
        <p className="text-sm text-destructive">{t.admin.error}: {error}</p>
      )}

      <div className="flex items-end gap-2">
        <div>
          <label className="text-xs text-muted-foreground">{t.admin.startDate}</label>
          <Input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">{t.admin.endDate}</label>
          <Input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </div>
        <button
          onClick={refresh}
          className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90"
        >
          {t.admin.filter}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {t.admin.totalRecords}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{records.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {t.admin.totalCost}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">${totalCost.toFixed(4)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {t.admin.totalTokens}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{totalTokens.toLocaleString()}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">{t.admin.records}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id} className="border-b text-left text-muted-foreground">
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        className="py-2 pr-4 cursor-pointer select-none"
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        <span className="inline-flex items-center gap-1">
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {{ asc: " ▲", desc: " ▼" }[header.column.getIsSorted() as string] ?? ""}
                        </span>
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.length === 0 && (
                  <tr>
                    <td colSpan={columns.length} className="py-8 text-center text-muted-foreground">
                      {t.admin.noUsageRecords}
                    </td>
                  </tr>
                )}
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id} className="border-b last:border-0">
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="py-2 pr-4">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex items-center justify-between text-sm">
            <span>
              {t.admin.page} {table.getState().pagination.pageIndex + 1} /{" "}
              {Math.max(1, table.getPageCount())}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => table.previousPage()}
                disabled={!table.getCanPreviousPage()}
                className="rounded-md border px-3 py-1 text-sm disabled:opacity-50"
              >
                {t.admin.previous}
              </button>
              <button
                onClick={() => table.nextPage()}
                disabled={!table.getCanNextPage()}
                className="rounded-md border px-3 py-1 text-sm disabled:opacity-50"
              >
                {t.admin.next}
              </button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
