"use client";

import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  DatabaseIcon,
  Loader2Icon,
  TimerIcon,
  XCircleIcon,
} from "@/components/ui/icons";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useI18n } from "@/core/i18n/hooks";
import { useHealthSummary } from "@/core/knowledge-base";

export function KbHealthSummary() {
  const { t } = useI18n();
  const { data: summary, isLoading } = useHealthSummary();

  if (isLoading) {
    return (
      <div className="text-muted-foreground flex items-center justify-center py-12">
        <Loader2Icon className="mr-2 h-4 w-4 animate-spin" />
        {t.knowledgeBase.healthSummaryLoading}
      </div>
    );
  }

  if (!summary || summary.total_kbs === 0) {
    return (
      <div className="text-muted-foreground py-12 text-center text-sm">
        {t.knowledgeBase.healthSummaryEmpty}
      </div>
    );
  }

  const successRate = Math.round(summary.index_success_rate * 100);
  const p95 = summary.retrieval.p95_latency_ms;
  const latencyColor =
    summary.retrieval.total_queries > 0
      ? p95 < 500
        ? "text-green-600"
        : p95 < 2000
          ? "text-yellow-600"
          : "text-red-500"
      : "text-muted-foreground";

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">
              {t.knowledgeBase.healthSummaryIndexSuccess}
            </CardTitle>
            <CheckCircle2Icon className="h-4 w-4 text-green-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{successRate}%</div>
            <Progress value={successRate} className="mt-2 h-1.5" />
            <p className="text-muted-foreground mt-1 text-xs">
              {t.knowledgeBase.healthSummaryDocumentsCount(
                summary.documents.ready,
                summary.documents.total,
              )}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">
              {t.knowledgeBase.healthSummaryRetrievalP95}
            </CardTitle>
            <TimerIcon className="h-4 w-4 text-blue-600" />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${latencyColor}`}>
              {summary.retrieval.total_queries > 0
                ? `${p95.toFixed(0)} ms`
                : "-"}
            </div>
            <p className="text-muted-foreground mt-1 text-xs">
              {t.knowledgeBase.healthSummaryQueriesAcross(
                summary.retrieval.total_queries,
                summary.total_kbs,
              )}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">
              {t.knowledgeBase.title}
            </CardTitle>
            <DatabaseIcon className="h-4 w-4 text-purple-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{summary.total_kbs}</div>
            <p className="text-muted-foreground mt-1 text-xs">
              {summary.documents.indexing > 0
                ? t.knowledgeBase.healthSummaryIndexingInProgress(
                    summary.documents.indexing,
                  )
                : t.knowledgeBase.healthSummaryAllIdle}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">
              {t.knowledgeBase.healthSummaryFailedDocs}
            </CardTitle>
            <AlertTriangleIcon
              className={`h-4 w-4 ${summary.documents.failed > 0 ? "text-red-500" : "text-muted-foreground"}`}
            />
          </CardHeader>
          <CardContent>
            <div
              className={`text-2xl font-bold ${summary.documents.failed > 0 ? "text-red-600" : ""}`}
            >
              {summary.documents.failed}
            </div>
            <p className="text-muted-foreground mt-1 text-xs">
              {t.knowledgeBase.healthSummaryErrorCategories(
                Object.keys(summary.failure_by_type).length,
              )}
            </p>
          </CardContent>
        </Card>
      </div>

      {Object.keys(summary.failure_by_type).length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">
              {t.knowledgeBase.healthSummaryFailureByType}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {Object.entries(summary.failure_by_type).map(([cat, count]) => (
                <span
                  key={cat}
                  className="inline-flex items-center gap-1 rounded-full border border-red-200 bg-red-50 px-2.5 py-0.5 text-xs font-medium text-red-700"
                >
                  <XCircleIcon className="h-3 w-3" />
                  {cat}: {count}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {summary.recent_failures.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">
              {t.knowledgeBase.healthSummaryRecentFailures(
                summary.recent_failures.length,
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="max-h-48 space-y-1 overflow-y-auto">
              {summary.recent_failures.slice(0, 10).map((failure) => (
                <div
                  key={failure.job_id}
                  className="flex items-start gap-2 rounded border border-red-200 bg-red-50 px-2 py-1 text-xs"
                >
                  <XCircleIcon className="mt-0.5 h-3 w-3 shrink-0 text-red-500" />
                  <span className="text-muted-foreground line-clamp-2 break-all">
                    {failure.error ?? t.knowledgeBase.healthSummaryUnknownError}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">
            {t.knowledgeBase.healthSummaryPerKnowledgeBase}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left">
                  <th className="pb-2 font-medium">{t.knowledgeBase.name}</th>
                  <th className="pb-2 text-right font-medium">
                    {t.knowledgeBase.documents}
                  </th>
                  <th className="pb-2 text-right font-medium">
                    {t.knowledgeBase.indexedCount}
                  </th>
                  <th className="pb-2 text-right font-medium">
                    {t.knowledgeBase.failedCount}
                  </th>
                  <th className="pb-2 text-right font-medium">
                    {t.knowledgeBase.retrievalLatencyAvg}
                  </th>
                  <th className="pb-2 text-right font-medium">
                    {t.knowledgeBase.totalQueries}
                  </th>
                </tr>
              </thead>
              <tbody>
                {summary.per_kb.map((kb) => (
                  <tr key={kb.kb_id} className="border-b last:border-0">
                    <td className="py-2 font-medium">{kb.kb_name}</td>
                    <td className="py-2 text-right">{kb.total}</td>
                    <td className="py-2 text-right text-green-600">
                      {kb.ready}
                    </td>
                    <td
                      className={`py-2 text-right ${kb.failed > 0 ? "font-medium text-red-600" : ""}`}
                    >
                      {kb.failed}
                    </td>
                    <td className="py-2 text-right">
                      {kb.total_queries > 0
                        ? `${kb.avg_retrieval_latency_ms.toFixed(0)} ms`
                        : "-"}
                    </td>
                    <td className="py-2 text-right">{kb.total_queries}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
