"use client";

import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  ClockIcon,
  GaugeIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useI18n } from "@/core/i18n/hooks";
import { useIndexStats } from "@/core/knowledge-base";

interface KbIndexHealthCardProps {
  kbId: string;
}

export function KbIndexHealthCard({ kbId }: KbIndexHealthCardProps) {
  const { t } = useI18n();
  const { data: stats, isLoading } = useIndexStats(kbId);

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">
            {t.knowledgeBase.indexHealth}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-muted-foreground flex h-16 items-center justify-center text-xs">
            <Loader2Icon className="mr-2 h-3.5 w-3.5 animate-spin" />
            {t.common.loading}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!stats || stats.total === 0) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">
            {t.knowledgeBase.indexHealth}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-muted-foreground flex h-16 items-center justify-center text-xs">
            {t.knowledgeBase.noIndexData}
          </div>
        </CardContent>
      </Card>
    );
  }

  const completionRate =
    stats.total > 0 ? Math.round((stats.ready / stats.total) * 100) : 0;

  // Retrieval health indicator based on p95 latency thresholds
  const p95 = stats.p95_retrieval_latency_ms;
  const retrievalHealth =
    stats.total_queries > 0
      ? p95 < 500
        ? "good"
        : p95 < 2000
          ? "warn"
          : "slow"
      : "idle";

  const retrievalHealthColors: Record<string, string> = {
    good: "text-green-600",
    warn: "text-yellow-600",
    slow: "text-red-500",
    idle: "text-muted-foreground",
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          {t.knowledgeBase.indexHealth}
          <Badge
            variant={stats.failed > 0 ? "destructive" : "default"}
            className="text-xs"
          >
            {completionRate}%
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {/* Progress bar */}
        <Progress value={completionRate} className="h-1.5" />

        {/* Status counts */}
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="text-muted-foreground inline-flex items-center gap-1">
            <CheckCircle2Icon className="h-3 w-3 text-green-600" />
            {stats.ready} {t.knowledgeBase.indexedCount}
          </span>
          {stats.indexing > 0 && (
            <span className="text-muted-foreground inline-flex items-center gap-1">
              <Loader2Icon className="h-3 w-3 animate-spin text-blue-600" />
              {stats.indexing} {t.knowledgeBase.indexingCount}
            </span>
          )}
          {stats.pending > 0 && (
            <span className="text-muted-foreground inline-flex items-center gap-1">
              <ClockIcon className="h-3 w-3 text-yellow-600" />
              {stats.pending} {t.knowledgeBase.pendingCount}
            </span>
          )}
          {stats.failed > 0 && (
            <span className="inline-flex items-center gap-1 text-red-600">
              <AlertTriangleIcon className="h-3 w-3" />
              {stats.failed} {t.knowledgeBase.failedCount}
            </span>
          )}
        </div>

        {/* Latency metrics */}
        <div className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span>
            {t.knowledgeBase.indexDuration}: {stats.avg_index_duration_ms.toFixed(0)} ms
          </span>
          <span className={retrievalHealthColors[retrievalHealth]}>
            {t.knowledgeBase.retrievalLatency}: {stats.p95_retrieval_latency_ms.toFixed(0)} ms
          </span>
          <span>
            {t.knowledgeBase.retrievalLatencyAvg}: {stats.avg_retrieval_latency_ms.toFixed(0)} ms
          </span>
          <span>
            {t.knowledgeBase.totalQueries}: {stats.total_queries}
          </span>
        </div>

        {/* Recent failures */}
        {stats.recent_failures.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-red-600">
              {t.knowledgeBase.indexFailed} ({stats.recent_failures.length})
            </span>
            <div className="max-h-24 space-y-1 overflow-y-auto">
              {stats.recent_failures.map((f) => (
                <div
                  key={f.job_id}
                  className="text-muted-foreground flex items-start gap-2 rounded border border-red-200 bg-red-50 px-2 py-1 text-xs"
                >
                  <XCircleIcon className="mt-0.5 h-3 w-3 shrink-0 text-red-500" />
                  <span className="line-clamp-2 break-all">
                    {f.error ?? "Unknown error"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
