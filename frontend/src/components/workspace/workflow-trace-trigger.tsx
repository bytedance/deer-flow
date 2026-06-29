"use client";

import {
  ActivityIcon,
  CheckCircle2Icon,
  CircleDashedIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useWorkflowTraceByRun } from "@/core/workflows/hooks";
import { cn } from "@/lib/utils";

function shortId(value?: string | null) {
  if (!value) {
    return "-";
  }
  return value.length > 12 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value;
}

function statusClass(status?: string) {
  if (status === "succeeded") {
    return "text-emerald-600 dark:text-emerald-400";
  }
  if (status === "failed" || status === "cancelled" || status === "orphaned") {
    return "text-destructive";
  }
  if (status === "running" || status === "run_created") {
    return "text-sky-600 dark:text-sky-400";
  }
  return "text-muted-foreground";
}

function StatusIcon({ status }: { status?: string }) {
  if (status === "succeeded") {
    return <CheckCircle2Icon className="size-3.5" />;
  }
  if (status === "failed" || status === "cancelled" || status === "orphaned") {
    return <XCircleIcon className="size-3.5" />;
  }
  if (status === "running" || status === "run_created") {
    return <Loader2Icon className="size-3.5 animate-spin" />;
  }
  return <CircleDashedIcon className="size-3.5" />;
}

export function WorkflowTraceTrigger({
  runId,
  enabled = true,
}: {
  runId?: string | null;
  enabled?: boolean;
}) {
  const trace = useWorkflowTraceByRun(runId, { enabled: enabled && Boolean(runId) });
  const workflow = trace.data?.workflow;
  const status = workflow?.status;

  if (!runId || trace.data === null) {
    return null;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          aria-label="Trace"
          className={cn("gap-1.5", status && statusClass(status))}
          disabled={!enabled}
          size="sm"
          type="button"
          variant="ghost"
        >
          {trace.isLoading ? (
            <Loader2Icon className="size-4 animate-spin" />
          ) : (
            <ActivityIcon className="size-4" />
          )}
          <span className="hidden sm:inline">Trace</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-96 max-w-[calc(100vw-2rem)]">
        <DropdownMenuLabel className="flex items-center justify-between gap-3">
          <span>Durable Run Trace</span>
          <span className={cn("inline-flex items-center gap-1 text-xs", statusClass(status))}>
            <StatusIcon status={status} />
            {status ?? "loading"}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <div className="space-y-2 px-2 py-2 text-xs">
          <div className="grid grid-cols-[88px_1fr] gap-2">
            <span className="text-muted-foreground">workflow</span>
            <span className="font-mono">{shortId(workflow?.workflow_id)}</span>
            <span className="text-muted-foreground">run</span>
            <span className="font-mono">{shortId(runId)}</span>
            <span className="text-muted-foreground">source</span>
            <span className="truncate">{workflow?.source ?? "-"}</span>
          </div>
          <DropdownMenuSeparator />
          <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
            {(trace.data?.timeline ?? []).slice(0, 12).map((event, index) => (
              <div
                className="grid grid-cols-[16px_1fr] gap-2"
                key={`${event.kind}/${event.seq ?? index}/${event.event_type}`}
              >
                <span
                  className={cn(
                    "mt-1 size-2 rounded-full",
                    event.kind === "workflow_event" ? "bg-primary" : "bg-muted-foreground",
                  )}
                />
                <div className="min-w-0">
                  <div className="truncate font-medium">{event.event_type}</div>
                  <div className="text-muted-foreground flex min-w-0 gap-2">
                    <span>{event.kind === "workflow_event" ? "workflow" : "run"}</span>
                    {event.created_at && (
                      <span className="truncate">{new Date(event.created_at).toLocaleTimeString()}</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
            {trace.isLoading && (
              <div className="text-muted-foreground flex items-center gap-2">
                <Loader2Icon className="size-3 animate-spin" />
                Loading trace
              </div>
            )}
            {trace.isError && (
              <div className="text-destructive">Trace unavailable</div>
            )}
          </div>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
