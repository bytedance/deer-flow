import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import type { Translations } from "@/core/i18n/locales/types";
import { formatRunDuration } from "@/core/usage/format";
import type { UsageRun } from "@/core/usage/types";

export function UsageRuns({
  runs,
  locale,
  text,
}: {
  runs: UsageRun[];
  locale: string;
  text: Translations["usage"];
}) {
  if (runs.length === 0)
    return (
      <p className="text-muted-foreground py-8 text-center text-sm">
        {text.noRuns}
      </p>
    );
  const statusLabels: Record<string, string> = {
    pending: text.pending,
    running: text.running,
    success: text.success,
    error: text.error,
    timeout: text.timeout,
    interrupted: text.interrupted,
  };
  const cell = "px-4 py-3 text-right whitespace-nowrap tabular-nums";
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label={text.recentRuns}>
        <thead>
          <tr className="text-muted-foreground border-b">
            <th scope="col" className="px-4 py-3 text-left">
              {text.conversation}
            </th>
            <th scope="col" className="px-4 py-3 text-left">
              {text.status}
            </th>
            <th scope="col" className="px-4 py-3 text-left">
              {text.model}
            </th>
            <th scope="col" className={cell}>
              {text.started}
            </th>
            <th scope="col" className={cell}>
              {text.duration}
            </th>
            <th scope="col" className={cell}>
              {text.tokens}
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const date = run.created_at ? new Date(run.created_at) : null;
            const dateLabel =
              date && Number.isFinite(date.getTime())
                ? new Intl.DateTimeFormat(locale, {
                    dateStyle: "short",
                    timeStyle: "short",
                  }).format(date)
                : text.unknown;
            return (
              <tr key={run.run_id} className="border-b align-top last:border-0">
                <th
                  scope="row"
                  className="max-w-72 min-w-40 px-4 py-3 text-left font-normal break-words"
                >
                  <Link
                    href={`/workspace/chats/${encodeURIComponent(run.thread_id)}`}
                    className="underline-offset-4 hover:underline"
                  >
                    {run.thread_title?.trim()
                      ? run.thread_title
                      : text.untitled}
                  </Link>
                  {run.error && (
                    <details className="mt-2 text-xs">
                      <summary className="text-muted-foreground cursor-pointer">
                        {text.details}
                      </summary>
                      <p className="mt-2 max-w-72 break-words whitespace-pre-wrap">
                        {run.error}
                      </p>
                    </details>
                  )}
                </th>
                <td className="px-4 py-3">
                  <Badge
                    variant={
                      run.status === "error" || run.status === "timeout"
                        ? "destructive"
                        : "secondary"
                    }
                  >
                    {Object.hasOwn(statusLabels, run.status)
                      ? statusLabels[run.status]
                      : text.unknownStatus}
                  </Badge>
                </td>
                <td className="max-w-48 px-4 py-3 break-words">
                  {run.model_name?.trim() ? run.model_name : text.unknown}
                </td>
                <td className={cell}>{dateLabel}</td>
                <td className={cell}>
                  {formatRunDuration(
                    run.duration_seconds,
                    locale,
                    text.unknown,
                  )}
                </td>
                <td className={cell}>
                  {run.total_tokens.toLocaleString(locale)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
