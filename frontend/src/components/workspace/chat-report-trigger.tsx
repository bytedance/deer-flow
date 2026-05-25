"use client";

import { FileBarChartIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip } from "@/components/workspace/tooltip";
import { buildCrossPageURL, logCrossPageNavigation } from "@/core/models/navigation";
import { useReportRuns } from "@/core/report-templates";

interface Props {
  threadId: string;
}

function artifactUrl(threadId: string, path: string): string {
  const idx = path.indexOf("user-data/");
  if (idx < 0) return path;
  const virtualSuffix = path.slice(idx);
  return `/api/threads/${threadId}/artifacts/mnt/${virtualSuffix}`;
}

/**
 * Button shown in the chat header when the current thread has associated
 * report runs. Each item links to the report run detail page, carrying
 * full CrossPageContext for traceability.
 */
export function ChatReportTrigger({ threadId }: Props) {
  const { runs, isLoading } = useReportRuns({ limit: 100 });

  const threadRuns = runs.filter((r) => r.thread_id === threadId);

  if (isLoading || threadRuns.length === 0) {
    return null;
  }

  return (
    <DropdownMenu>
      <Tooltip content="查看本对话生成的报告">
        <DropdownMenuTrigger asChild>
          <Button
            className="text-muted-foreground hover:text-foreground"
            variant="ghost"
          >
            <FileBarChartIcon />
            报告 ({threadRuns.length})
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" className="min-w-[260px]">
        {threadRuns.map((run) => {
          const ctx = {
            sourceType: "chat" as const,
            sourceId: threadId,
            threadId,
            runId: run.run_id,
          };
          const href = buildCrossPageURL(
            `/workspace/report-runs/${run.id}`,
            ctx,
          );
          const hasArtifacts =
            run.artifact_paths?.md || run.artifact_paths?.pdf;
          const isTerminal =
            run.status === "success" ||
            run.status === "failed" ||
            run.status === "cancelled";
          return (
            <DropdownMenuItem key={run.id} asChild>
              <div className="flex flex-col gap-1 py-1">
                <Link
                  href={href}
                  onClick={() => logCrossPageNavigation(ctx, "outbound")}
                  className="flex flex-col items-start gap-0.5"
                >
                  <span className="font-mono text-xs">{run.id}</span>
                  <span className="text-muted-foreground text-xs">
                    {run.template_version_ref ?? `v${run.template_version}`}
                    {" · "}
                    {run.status}
                  </span>
                </Link>
                {isTerminal && hasArtifacts && (
                  <div className="flex gap-2 mt-1">
                    {run.artifact_paths?.md && (
                      <a
                        href={artifactUrl(run.thread_id, run.artifact_paths.md)}
                        target="_blank"
                        rel="noreferrer"
                        onClick={() =>
                          logCrossPageNavigation(ctx, "outbound")
                        }
                        className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                      >
                        .md
                      </a>
                    )}
                    {run.artifact_paths?.pdf && (
                      <a
                        href={artifactUrl(run.thread_id, run.artifact_paths.pdf)}
                        target="_blank"
                        rel="noreferrer"
                        onClick={() =>
                          logCrossPageNavigation(ctx, "outbound")
                        }
                        className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                      >
                        .pdf
                      </a>
                    )}
                  </div>
                )}
              </div>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
