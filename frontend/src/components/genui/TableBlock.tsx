"use client";

import { useMemo, useState } from "react";

interface TableColumn {
  key: string;
  label: string;
  sortable?: boolean;
  width?: number;
  type?: "text" | "image";
}

interface TableBlockProps {
  block: {
    props: {
      columns: TableColumn[];
      data: Record<string, unknown>[];
      title?: string;
      sortable?: boolean;
      paginated?: boolean;
      page_size?: number;
      onRowSelect?: boolean;
    };
    callback_id?: string;
    onInteraction?: (callbackId: string, payload: Record<string, unknown>) => void;
  };
}

export default function TableBlock({ block }: TableBlockProps) {
  const { props, callback_id, onInteraction } = block;
  const { columns, data, title, sortable, paginated, page_size = 10, onRowSelect } = props;

  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);
  const [selectedRow, setSelectedRow] = useState<number | null>(null);

  const sortedData = useMemo(() => {
    if (!sortKey) return data;
    return [...data].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (aVal == null && bVal == null) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      const cmp = String(aVal as unknown).localeCompare(String(bVal as unknown), undefined, { numeric: true });
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [data, sortKey, sortDir]);

  const paginatedData = useMemo(() => {
    if (!paginated) return sortedData;
    const start = page * page_size;
    return sortedData.slice(start, start + page_size);
  }, [sortedData, paginated, page, page_size]);

  const totalPages = paginated ? Math.ceil(data.length / page_size) : 1;

  const handleSort = (key: string) => {
    if (!sortable) return;
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const handleRowClick = (row: Record<string, unknown>, index: number) => {
    if (!onRowSelect) return;
    setSelectedRow(index);
    if (callback_id && onInteraction) {
      onInteraction(callback_id, { selected_row: row, row_index: index });
    }
  };

  return (
    <div className="rounded-lg border bg-card" role="region" aria-label={title ?? "Data table"}>
      {title && (
        <div className="border-b px-4 py-3">
          <h3 className="text-sm font-medium">{title}</h3>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm" aria-label={title ?? "Data table"}>
          <thead>
            <tr className="border-b bg-muted/50">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`px-4 py-2 text-left font-medium text-muted-foreground ${
                    sortable ? "cursor-pointer select-none hover:text-foreground" : ""
                  }`}
                  style={col.width ? { width: col.width } : undefined}
                  onClick={() => handleSort(col.key)}
                  aria-sort={sortKey === col.key ? (sortDir === "asc" ? "ascending" : "descending") : undefined}
                  scope="col"
                >
                  {col.label}
                  {sortKey === col.key && (
                    <span className="ml-1" aria-hidden="true">{sortDir === "asc" ? "↑" : "↓"}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paginatedData.map((row, i) => {
              const globalIndex = paginated ? page * page_size + i : i;
              return (
                <tr
                  key={i}
                  className={`border-b last:border-0 ${
                    onRowSelect ? "cursor-pointer" : ""
                  } ${selectedRow === globalIndex ? "bg-primary/10" : "hover:bg-muted/30"}`}
                  onClick={() => handleRowClick(row, globalIndex)}
                  aria-selected={onRowSelect ? selectedRow === globalIndex : undefined}
                  role={onRowSelect ? "row" : undefined}
                >
                  {columns.map((col) => (
                    <td key={col.key} className="px-4 py-2">
                      {col.type === "image" && typeof row[col.key] === "string" && row[col.key] ? (
                        <img
                          src={row[col.key] as string}
                          alt={col.label}
                          loading="lazy"
                          className="max-h-16 max-w-24 rounded object-cover"
                        />
                      ) : (
                        String((row[col.key] ?? "") as unknown)
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {paginated && totalPages > 1 && (
        <nav className="flex items-center justify-between border-t px-4 py-2" aria-label="Table pagination">
          <span className="text-xs text-muted-foreground">
            Page {page + 1} of {totalPages}
          </span>
          <div className="flex gap-1">
            <button
              className="rounded px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              aria-label="Previous page"
            >
              Previous
            </button>
            <button
              className="rounded px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
              aria-label="Next page"
            >
              Next
            </button>
          </div>
        </nav>
      )}
    </div>
  );
}
