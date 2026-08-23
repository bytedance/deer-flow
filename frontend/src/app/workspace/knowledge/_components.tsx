"use client";

import { AlertTriangleIcon, LoaderCircleIcon, UsersIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { useI18n } from "@/core/i18n/hooks";
import { datasetParsingState, type KnowledgeDataset } from "@/core/knowledge";

export function SharedKnowledgeBanner() {
  const { t } = useI18n();
  return (
    <Alert className="border-amber-500/40 bg-amber-500/10">
      <UsersIcon className="text-amber-700 dark:text-amber-400" />
      <AlertTitle>{t.knowledge.sharedBannerTitle}</AlertTitle>
      <AlertDescription>{t.knowledge.sharedBannerDescription}</AlertDescription>
    </Alert>
  );
}

export function DatasetStatus({ dataset }: { dataset: KnowledgeDataset }) {
  const { t } = useI18n();
  const state = datasetParsingState(dataset);

  if (state.kind === "parsing") {
    return (
      <div className="flex min-w-32 flex-col gap-1.5">
        <Badge
          variant="secondary"
          className="bg-blue-500/10 text-blue-700 dark:text-blue-300"
        >
          <LoaderCircleIcon className="animate-spin" />
          {t.knowledge.status.parsing} {state.completed}/{state.total}
        </Badge>
        <Progress value={state.percent} className="h-1.5" />
      </div>
    );
  }

  if (state.kind === "failed") {
    return (
      <Badge variant="destructive">
        <AlertTriangleIcon />
        {t.knowledge.status.failed}
      </Badge>
    );
  }

  return (
    <Badge variant={state.kind === "ready" ? "default" : "outline"}>
      {state.kind === "ready"
        ? t.knowledge.status.ready
        : t.knowledge.status.empty}
    </Badge>
  );
}
