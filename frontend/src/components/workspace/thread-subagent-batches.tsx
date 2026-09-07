"use client";

import {
  ArchiveIcon,
  CirclePauseIcon,
  CirclePlayIcon,
  CircleStopIcon,
  DownloadIcon,
  Layers3Icon,
  LoaderCircleIcon,
  RotateCcwIcon,
} from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { useSubagentBatchesCapability } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import {
  completedSubagentBatchItems,
  isActiveSubagentBatch,
  subagentBatchProgress,
  subagentBatchResultsUrl,
  type SubagentBatch,
  type SubagentBatchItem,
  useControlSubagentBatch,
  useRetrySubagentBatchItem,
  useSubagentBatchItems,
  useSubagentBatches,
} from "@/core/subagent-batches";

export function ThreadSubagentBatches({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  const { repositoryAvailable, workerRunning } = useSubagentBatchesCapability();
  const batchesQuery = useSubagentBatches(threadId, {
    enabled: repositoryAvailable,
    polling: workerRunning,
  });
  const control = useControlSubagentBatch(threadId);
  const batches = batchesQuery.data ?? [];
  const activeCount = batches.filter(isActiveSubagentBatch).length;

  const hasVisibleSurface =
    repositoryAvailable &&
    (workerRunning ||
      batchesQuery.isLoading ||
      batchesQuery.isError ||
      batches.length > 0);

  if (!hasVisibleSurface) return null;

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="relative"
          aria-label={t.subagentBatches.label}
          data-testid="subagent-batches-trigger"
        >
          <Layers3Icon />
          <span className="hidden xl:inline">{t.subagentBatches.label}</span>
          {activeCount > 0 && (
            <span className="bg-primary text-primary-foreground grid size-4 place-items-center rounded-full text-[10px] font-semibold">
              {activeCount > 9 ? "9+" : activeCount}
            </span>
          )}
        </Button>
      </SheetTrigger>
      <SheetContent className="w-[min(94vw,520px)] gap-0 p-0 sm:max-w-[520px]">
        <SheetHeader className="border-border border-b px-5 py-4">
          <SheetTitle className="flex items-center gap-2">
            <Layers3Icon className="size-4" />
            {t.subagentBatches.title}
          </SheetTitle>
          <SheetDescription>{t.subagentBatches.description}</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {!workerRunning && (
            <div
              role="status"
              className="border-border bg-muted/50 text-muted-foreground mb-4 rounded-xl border p-3 text-xs"
            >
              {t.subagentBatches.workerUnavailable}
            </div>
          )}
          {batchesQuery.isLoading ? (
            <div className="text-muted-foreground flex justify-center gap-2 py-12 text-sm">
              <LoaderCircleIcon className="size-4 animate-spin" />
              {t.common.loading}
            </div>
          ) : batchesQuery.isError ? (
            <div className="border-destructive/30 bg-destructive/5 rounded-xl border p-4 text-sm">
              <p className="text-destructive font-medium">
                {t.subagentBatches.loadFailed}
              </p>
              <p className="text-muted-foreground mt-1 text-xs">
                {batchesQuery.error.message}
              </p>
            </div>
          ) : batches.length === 0 ? (
            <div className="text-muted-foreground flex flex-col items-center px-6 py-14 text-center">
              <ArchiveIcon className="mb-3 size-8 opacity-40" />
              <p className="text-foreground text-sm font-medium">
                {t.subagentBatches.empty}
              </p>
              <p className="mt-1 text-xs">{t.subagentBatches.emptyHint}</p>
            </div>
          ) : (
            <div className="space-y-3">
              {batches.map((batch) => (
                <BatchCard
                  key={batch.id}
                  threadId={threadId}
                  batch={batch}
                  workerRunning={workerRunning}
                  controlling={
                    control.isPending && control.variables?.batchId === batch.id
                  }
                  onControl={(action) =>
                    control.mutate({ batchId: batch.id, action })
                  }
                />
              ))}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function BatchCard({
  threadId,
  batch,
  workerRunning,
  controlling,
  onControl,
}: {
  threadId: string;
  batch: SubagentBatch;
  workerRunning: boolean;
  controlling: boolean;
  onControl: (action: "pause" | "resume" | "cancel") => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const completed = completedSubagentBatchItems(batch);
  const active = isActiveSubagentBatch(batch);
  const labels = t.subagentBatches.status;

  return (
    <article
      className="border-border bg-card rounded-xl border p-3"
      data-testid={`subagent-batch-${batch.id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium" title={batch.title}>
            {batch.title}
          </p>
          <p className="text-muted-foreground mt-1 text-xs">
            {batch.subagent_type} ·{" "}
            {t.subagentBatches.limits(
              batch.max_live_items,
              batch.max_running_items,
            )}
          </p>
        </div>
        <Badge variant="outline">{labels[batch.status]}</Badge>
      </div>
      <Progress className="mt-3 h-1.5" value={subagentBatchProgress(batch)} />
      <div className="text-muted-foreground mt-1.5 flex flex-wrap gap-x-3 text-[11px]">
        <span>{t.subagentBatches.progress(completed, batch.total_items)}</span>
        <span>
          {batch.counts.running} {labels.running.toLowerCase()}
        </span>
        {batch.counts.failed > 0 && (
          <span className="text-destructive">
            {batch.counts.failed} {labels.failed.toLowerCase()}
          </span>
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? t.subagentBatches.hideItems : t.subagentBatches.viewItems}
        </Button>
        {batch.status === "running" || batch.status === "queued" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!workerRunning || controlling}
            onClick={() => onControl("pause")}
          >
            <CirclePauseIcon /> {t.subagentBatches.pause}
          </Button>
        ) : batch.status === "paused" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!workerRunning || controlling}
            onClick={() => onControl("resume")}
          >
            <CirclePlayIcon /> {t.subagentBatches.resume}
          </Button>
        ) : null}
        {active && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!workerRunning || controlling}
            onClick={() => onControl("cancel")}
          >
            <CircleStopIcon /> {t.subagentBatches.cancel}
          </Button>
        )}
        <Button asChild type="button" size="sm" variant="outline">
          <a href={subagentBatchResultsUrl(threadId, batch.id)} download>
            <DownloadIcon /> {t.subagentBatches.exportResults}
          </a>
        </Button>
      </div>
      {open && (
        <BatchItems
          threadId={threadId}
          batch={batch}
          workerRunning={workerRunning}
        />
      )}
    </article>
  );
}

function BatchItems({
  threadId,
  batch,
  workerRunning,
}: {
  threadId: string;
  batch: SubagentBatch;
  workerRunning: boolean;
}) {
  const { t } = useI18n();
  const query = useSubagentBatchItems(threadId, batch.id, {
    polling: workerRunning,
  });
  const retry = useRetrySubagentBatchItem(threadId, batch.id);
  if (query.isLoading) {
    return (
      <div className="text-muted-foreground mt-3 border-t pt-3 text-xs">
        {t.common.loading}
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className="text-destructive mt-3 border-t pt-3 text-xs">
        {t.subagentBatches.itemsFailed}: {query.error.message}
      </div>
    );
  }
  return (
    <div className="border-border mt-3 max-h-72 space-y-2 overflow-y-auto border-t pt-3">
      {(query.data?.pages.flat() ?? []).map((item) => (
        <BatchItemRow
          key={item.id}
          item={item}
          workerRunning={workerRunning}
          retrying={retry.isPending && retry.variables === item.id}
          onRetry={() => retry.mutate(item.id)}
        />
      ))}
      {query.hasNextPage && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="w-full"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage && (
            <LoaderCircleIcon className="animate-spin" />
          )}
          {t.common.loadMore}
        </Button>
      )}
    </div>
  );
}

function BatchItemRow({
  item,
  workerRunning,
  retrying,
  onRetry,
}: {
  item: SubagentBatchItem;
  workerRunning: boolean;
  retrying: boolean;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="bg-muted/40 rounded-lg p-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate font-medium" title={item.item_key}>
          {item.item_key}
        </span>
        <Badge variant="outline">{item.status}</Badge>
      </div>
      {item.result_preview && (
        <p className="mt-1 line-clamp-3 whitespace-pre-wrap">
          {item.result_preview}
        </p>
      )}
      {item.error && (
        <p className="text-destructive mt-1 break-words">{item.error}</p>
      )}
      {item.status === "failed" && (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={!workerRunning || retrying}
          className="mt-1"
          onClick={onRetry}
        >
          {retrying ? (
            <LoaderCircleIcon className="animate-spin" />
          ) : (
            <RotateCcwIcon />
          )}
          {t.subagentBatches.retryItem}
        </Button>
      )}
    </div>
  );
}
