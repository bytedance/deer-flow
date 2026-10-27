import { DatabaseIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import {
  KNOWLEDGE_SCOPE_KEY,
  readKnowledgeScopeSnapshot,
} from "@/core/knowledge";

export function KnowledgeScopeSummary({
  additionalKwargs,
}: {
  additionalKwargs: Record<string, unknown> | undefined;
}) {
  const { t } = useI18n();
  const snapshot = readKnowledgeScopeSnapshot(
    additionalKwargs?.[KNOWLEDGE_SCOPE_KEY],
  );
  if (!snapshot) return null;

  if (snapshot.mode === "all") {
    return <SummaryText text={t.knowledge.scope.historyAll} />;
  }
  if (snapshot.mode === "disabled") {
    return <SummaryText text={t.knowledge.scope.historyDisabled} />;
  }

  const datasetCount = snapshot.dataset_ids?.length ?? 0;
  const documentCount =
    snapshot.document_filters?.reduce(
      (total, filter) => total + filter.document_ids.length,
      0,
    ) ?? 0;
  const datasetNames = snapshot.display?.datasets
    .map((dataset) => dataset.name)
    .filter(Boolean);
  const documentNames = snapshot.display?.datasets
    .flatMap(
      (dataset) => dataset.documents?.map((document) => document.name) ?? [],
    )
    .filter(Boolean);
  const details = [
    datasetNames?.length ? datasetNames.join("、") : null,
    documentNames?.length ? documentNames.join("、") : null,
  ].filter((value): value is string => Boolean(value));
  return (
    <SummaryText
      text={t.knowledge.scope.historySelected(datasetCount, documentCount)}
      details={details.join(" · ") || undefined}
    />
  );
}

function SummaryText({ text, details }: { text: string; details?: string }) {
  return (
    <div
      className="text-muted-foreground flex max-w-full items-center justify-end gap-1 text-xs"
      data-testid="message-knowledge-scope"
      title={details}
    >
      <DatabaseIcon className="size-3 shrink-0" />
      <span className="truncate">
        {details ? `${text} · ${details}` : text}
      </span>
    </div>
  );
}
