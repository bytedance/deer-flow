"use client";

import {
  ChevronLeftIcon,
  ChevronRightIcon,
  LoaderIcon,
  Table2Icon,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useDelimitedPreview } from "@/core/artifacts/use-delimited-preview";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";

const PAGE_SIZE = 50;
const MAX_DATA_ROWS = 200;

interface TablePreviewProps {
  content: string;
  delimiter: "," | "\t";
  truncated: boolean;
  identity: string;
  active?: boolean;
}

export function ArtifactTablePreview(props: TablePreviewProps) {
  return <TablePreview key={props.identity} {...props} />;
}

function TablePreview({
  content,
  delimiter,
  truncated,
  identity,
  active = true,
}: TablePreviewProps) {
  const { t } = useI18n();
  const labels = t.artifactTable;
  const { result, status, retry } = useDelimitedPreview({
    content,
    delimiter,
    truncated,
    identity,
    active,
  });
  const [hasHeader, setHasHeader] = useState(true);
  const [pagination, setPagination] = useState({ content, page: 0 });
  const [cell, setCell] = useState<{
    value: string;
    label: string;
    content: string;
  } | null>(null);
  const [copyStatus, setCopyStatus] = useState("");
  const page = pagination.content === content ? pagination.page : 0;
  const rows =
    result?.rows.slice(
      hasHeader ? 1 : 0,
      (hasHeader ? 1 : 0) + MAX_DATA_ROWS,
    ) ?? [];
  const limited = Boolean(
    result?.limited === true ||
    (result && result.rows.length > MAX_DATA_ROWS + Number(hasHeader)),
  );
  const columnCount = Math.min(result?.columnCount ?? 0, 50);
  const start = Math.min(page * PAGE_SIZE, Math.max(0, rows.length - 1));
  const end = Math.min(start + PAGE_SIZE, rows.length);
  const columns = Array.from({ length: columnCount }, (_, index) => index);

  return (
    <div
      hidden={!active}
      className="flex h-full min-h-0 flex-col"
      data-testid="artifact-table-preview"
    >
      {status === "error" ? (
        <div
          role="status"
          className="text-muted-foreground flex flex-col items-center gap-3 p-8 text-center text-sm"
        >
          <p>{labels.failed}</p>
          <Button variant="outline" onClick={retry}>
            {labels.retry}
          </Button>
        </div>
      ) : status === "loading" || !result ? (
        <div
          role="status"
          className="text-muted-foreground flex items-center gap-2 p-6 text-sm"
        >
          <LoaderIcon className="size-4 animate-spin" />
          {t.common.loading}
        </div>
      ) : result.rows.length === 0 ? (
        <p role="status" className="text-muted-foreground p-6 text-sm">
          {limited ? labels.incomplete : labels.empty}
        </p>
      ) : (
        <>
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-4 py-3 text-xs">
            <span className="flex items-center gap-2 font-medium">
              <Table2Icon className="text-muted-foreground size-4" />
              {limited ? labels.sample(rows.length) : labels.total(rows.length)}
            </span>
            <label className="text-muted-foreground flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={hasHeader}
                onChange={(event) => {
                  setHasHeader(event.target.checked);
                  setPagination({ content, page: 0 });
                }}
                className="accent-primary size-3.5"
              />
              {labels.header}
            </label>
          </div>
          {(result.columnCount > 50 || result.unevenRows) && (
            <p
              role="status"
              className="bg-muted/30 text-muted-foreground border-b px-4 py-2 text-xs"
            >
              {result.columnCount > 50 && labels.columnsLimited}{" "}
              {result.unevenRows && labels.uneven}
            </p>
          )}
          <div
            className="min-h-0 flex-1 overflow-auto"
            tabIndex={0}
            role="region"
            aria-label={labels.title}
          >
            <table
              aria-label={labels.title}
              className="w-full table-fixed border-separate border-spacing-0 text-sm"
              style={{ minWidth: Math.max(320, columnCount * 180 + 48) }}
            >
              <colgroup>
                <col style={{ width: 48 }} />
                {columns.map((index) => (
                  <col key={index} />
                ))}
              </colgroup>
              <thead className="bg-muted sticky top-0 z-10">
                <tr>
                  <th
                    scope="col"
                    className="text-muted-foreground border-b px-3 py-3 text-xs font-normal"
                  >
                    #
                  </th>
                  {columns.map((index) => (
                    <th
                      key={index}
                      scope="col"
                      className="truncate border-b border-l px-3 py-3 text-left text-xs font-medium"
                      title={hasHeader ? result.rows[0]?.[index] : undefined}
                    >
                      {hasHeader
                        ? (result.rows[0]?.[index] ?? "")
                        : labels.column(index + 1)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(start, end).map((row, rowIndex) => (
                  <tr
                    key={start + rowIndex}
                    className="even:bg-muted/20 hover:bg-muted/40"
                  >
                    <th
                      scope="row"
                      className="text-muted-foreground border-b px-3 py-2.5 text-right text-xs font-normal tabular-nums"
                    >
                      {start + rowIndex + 1}
                    </th>
                    {columns.map((column) => {
                      const value = row[column];
                      const expandable =
                        value !== undefined &&
                        (value.length > 120 || /[\r\n]/.test(value));
                      return (
                        <td
                          key={column}
                          className="border-b border-l px-3 py-2.5 align-top"
                        >
                          <div className="truncate">
                            {value === undefined ? (
                              <span className="text-muted-foreground text-xs italic">
                                {labels.missing}
                              </span>
                            ) : expandable ? (
                              <button
                                type="button"
                                className="max-w-full cursor-pointer truncate text-left underline underline-offset-4"
                                aria-label={labels.cell(
                                  start + rowIndex + 1,
                                  column + 1,
                                )}
                                onClick={() => {
                                  setCell({
                                    content,
                                    value,
                                    label: labels.cell(
                                      start + rowIndex + 1,
                                      column + 1,
                                    ),
                                  });
                                  setCopyStatus("");
                                }}
                              >
                                {value.slice(0, 120)}
                              </button>
                            ) : (
                              <span className="whitespace-pre" title={value}>
                                {value}
                              </span>
                            )}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="text-muted-foreground flex shrink-0 items-center justify-between border-t px-4 py-2 text-xs">
            <span aria-live="polite">
              {labels.range(rows.length ? start + 1 : 0, end, limited)}
            </span>
            <div className="flex gap-1">
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={labels.previous}
                disabled={page === 0}
                onClick={() => setPagination({ content, page: page - 1 })}
              >
                <ChevronLeftIcon className="size-4" />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={labels.next}
                disabled={end >= rows.length}
                onClick={() => setPagination({ content, page: page + 1 })}
              >
                <ChevronRightIcon className="size-4" />
              </Button>
            </div>
          </div>
        </>
      )}
      <Dialog
        open={cell !== null && cell.content === content && active}
        onOpenChange={(open) => {
          if (!open) setCell(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{labels.cellValue}</DialogTitle>
            <DialogDescription>{cell?.label}</DialogDescription>
          </DialogHeader>
          <textarea
            aria-label={labels.cellValue}
            readOnly
            value={cell?.value ?? ""}
            className="h-64 w-full resize-none rounded-md border p-3 font-mono text-sm"
          />
          <div className="flex items-center justify-end gap-3">
            <span role="status" className="text-muted-foreground text-xs">
              {copyStatus}
            </span>
            <Button
              variant="outline"
              onClick={() => {
                void writeTextToClipboard(cell?.value ?? "")
                  .then((ok) =>
                    setCopyStatus(
                      ok
                        ? t.clipboard.copiedToClipboard
                        : t.clipboard.failedToCopyToClipboard,
                    ),
                  )
                  .catch(() =>
                    setCopyStatus(t.clipboard.failedToCopyToClipboard),
                  );
              }}
            >
              {t.clipboard.copyToClipboard}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
