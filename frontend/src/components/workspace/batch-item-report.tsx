"use client";

import { LoaderCircleIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  SafeStreamdown,
  toStreamdownComponents,
} from "@/core/streamdown/components";
import { streamdownPluginsWithoutRawHtml } from "@/core/streamdown/plugins";
import {
  type SubagentBatchItem,
  useSubagentBatchResult,
} from "@/core/subagent-batches";

import { KnowledgeSourcesProvider } from "./citations/knowledge-source";
import { createMarkdownLinkComponent } from "./messages/markdown-link";

type ReportProps = {
  threadId: string;
  batchId: string;
  item: SubagentBatchItem;
  workerRunning: boolean;
};

export function BatchItemReport(props: ReportProps) {
  const { user } = useAuth();
  const inspectable =
    ["succeeded", "failed", "cancelled"].includes(props.item.status) ||
    !!props.item.result_preview;
  // Changing thread, item or principal also removes nested source dialogs.
  return user && inspectable ? (
    <ReportDialog
      key={`${user.id}:${props.threadId}:${props.batchId}:${props.item.position}`}
      {...props}
      userId={user.id}
    />
  ) : null;
}

function ReportDialog(props: ReportProps & { userId: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="ghost" className="mt-1">
          {t.subagentBatches.viewReport}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] min-w-0 overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{t.subagentBatches.savedReport}</DialogTitle>
          <DialogDescription className="break-words">
            {props.item.item_key}
          </DialogDescription>
        </DialogHeader>
        {open && <ReportBody {...props} />}
      </DialogContent>
    </Dialog>
  );
}

function ReportBody({
  threadId,
  batchId,
  item,
  userId,
  workerRunning,
}: ReportProps & { userId: string }) {
  const { t } = useI18n();
  const labels = t.subagentBatches;
  const components = useMemo(
    () => toStreamdownComponents({ a: createMarkdownLinkComponent(threadId) }),
    [threadId],
  );
  const query = useSubagentBatchResult(
    threadId,
    batchId,
    item.position,
    userId,
    workerRunning,
  );
  if (query.isLoading)
    return (
      <p role="status">
        <LoaderCircleIcon className="inline size-4 animate-spin" />{" "}
        {t.common.loading}
      </p>
    );
  if (query.isError)
    return (
      <div role="alert" className="text-destructive text-sm">
        <p>
          {labels.reportFailed}: {query.error.message}
        </p>
        <Button
          type="button"
          variant="outline"
          onClick={() => void query.refetch()}
        >
          {labels.retryItem}
        </Button>
      </div>
    );
  const saved = query.data;
  if (!saved) return null;
  const verdict = saved.acceptance_verdict;
  const acceptance = !saved.acceptance_criteria?.length
    ? labels.noCriteria
    : verdict?.all_hold === true
      ? labels.accepted
      : verdict?.leaves.some((check) => check.checked && !check.holds)
        ? labels.unmet
        : labels.unverified;
  return (
    <div className="min-w-0 space-y-4" data-testid="batch-saved-report">
      <dl className="flex flex-wrap gap-4 text-sm">
        <div>
          <dt className="text-muted-foreground">{labels.execution}</dt>
          <dd>
            <Badge variant="outline">{saved.status}</Badge>
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{labels.acceptance}</dt>
          <dd>
            <Badge variant="outline">{acceptance}</Badge>
          </dd>
        </div>
      </dl>
      {saved.acceptance_criteria?.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm break-words">
          {saved.acceptance_criteria.map((criterion, index) => {
            const leaf = verdict?.leaves.find(
              (entry) => entry.criterion === criterion,
            );
            const outcome = leaf?.checked
              ? leaf.holds
                ? labels.accepted
                : labels.unmet
              : labels.unverified;
            return (
              <li key={`${index}:${criterion}`}>
                {criterion} <Badge variant="outline">{outcome}</Badge>
                {leaf?.detail && (
                  <p className="text-muted-foreground">{leaf.detail}</p>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}
      {saved.error && (
        <p className="text-destructive text-sm break-words">{saved.error}</p>
      )}
      {saved.result_truncated && (
        <p role="status" className="text-muted-foreground text-sm">
          {labels.reportTruncated}
        </p>
      )}
      {saved.result ? (
        <KnowledgeSourcesProvider
          key={saved.revision}
          savedEvidence={saved.evidence}
        >
          <SafeStreamdown
            {...streamdownPluginsWithoutRawHtml}
            mode="static"
            components={components}
          >
            {saved.result}
          </SafeStreamdown>
        </KnowledgeSourcesProvider>
      ) : (
        <p className="text-muted-foreground text-sm">{labels.noReport}</p>
      )}
      {!saved.evidence?.sources.length && (
        <p className="text-muted-foreground text-xs">
          {labels.evidenceUnavailable}
        </p>
      )}
      {(saved.evidence?.omitted_count ?? 0) > 0 && (
        <p className="text-muted-foreground text-xs">
          {labels.evidenceOmitted}
        </p>
      )}
    </div>
  );
}
