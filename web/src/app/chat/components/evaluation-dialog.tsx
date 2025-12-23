// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import {
  BookOpen,
  FileText,
  Image,
  Link2,
  Loader2,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button } from "~/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/dialog";
import { Progress } from "~/components/ui/progress";
import { evaluateReport, type EvaluationResult } from "~/core/api";
import { cn } from "~/lib/utils";

interface EvaluationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  reportContent: string;
  query: string;
  reportStyle?: string;
}

function GradeBadge({ grade }: { grade: string }) {
  const gradeColors: Record<string, string> = {
    "A+": "bg-emerald-500",
    A: "bg-emerald-500",
    "A-": "bg-emerald-400",
    "B+": "bg-blue-500",
    B: "bg-blue-500",
    "B-": "bg-blue-400",
    "C+": "bg-yellow-500",
    C: "bg-yellow-500",
    "C-": "bg-yellow-400",
    D: "bg-orange-500",
    F: "bg-red-500",
  };

  return (
    <div
      className={cn(
        "flex h-16 w-16 items-center justify-center rounded-full text-2xl font-bold text-white",
        gradeColors[grade] ?? "bg-gray-500",
      )}
    >
      {grade}
    </div>
  );
}

function MetricItem({
  icon: Icon,
  label,
  value,
  suffix,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number | string;
  suffix?: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <Icon className="text-muted-foreground h-4 w-4" />
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="ml-auto font-medium">
        {value}
        {suffix}
      </span>
    </div>
  );
}

export function EvaluationDialog({
  open,
  onOpenChange,
  reportContent,
  query,
  reportStyle,
}: EvaluationDialogProps) {
  const t = useTranslations("chat.evaluation");
  const [loading, setLoading] = useState(false);
  const [deepLoading, setDeepLoading] = useState(false);
  const [result, setResult] = useState<EvaluationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runEvaluation = useCallback(
    async (useLlm: boolean) => {
      if (useLlm) {
        setDeepLoading(true);
      } else {
        setLoading(true);
      }
      setError(null);

      try {
        const evalResult = await evaluateReport(
          reportContent,
          query,
          reportStyle,
          useLlm,
        );
        setResult(evalResult);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Evaluation failed");
      } finally {
        setLoading(false);
        setDeepLoading(false);
      }
    },
    [reportContent, query, reportStyle],
  );

  useEffect(() => {
    if (open && !result && !loading) {
      void runEvaluation(false);
    }
  }, [open, result, loading, runEvaluation]);

  useEffect(() => {
    if (!open) {
      setResult(null);
      setError(null);
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        {loading && !result ? (
          <div className="flex flex-col items-center justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
            <p className="text-muted-foreground mt-4 text-sm">
              {t("evaluating")}
            </p>
          </div>
        ) : error ? (
          <div className="py-4 text-center text-red-500">{error}</div>
        ) : result ? (
          <div className="space-y-6">
            {/* Grade and Score */}
            <div className="flex items-center gap-6">
              <GradeBadge grade={result.grade} />
              <div>
                <div className="text-3xl font-bold">{result.score}/10</div>
                <div className="text-muted-foreground text-sm">
                  {t("overallScore")}
                </div>
              </div>
            </div>

            {/* Metrics */}
            <div className="space-y-3">
              <h4 className="text-sm font-medium">{t("metrics")}</h4>
              <div className="bg-muted/50 space-y-2 rounded-lg p-3">
                <MetricItem
                  icon={FileText}
                  label={t("wordCount")}
                  value={result.metrics.word_count.toLocaleString()}
                />
                <MetricItem
                  icon={Link2}
                  label={t("citations")}
                  value={result.metrics.citation_count}
                />
                <MetricItem
                  icon={BookOpen}
                  label={t("sources")}
                  value={result.metrics.unique_sources}
                />
                <MetricItem
                  icon={Image}
                  label={t("images")}
                  value={result.metrics.image_count}
                />
                <div className="pt-2">
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">
                      {t("sectionCoverage")}
                    </span>
                    <span className="font-medium">
                      {Math.round(result.metrics.section_coverage_score * 100)}%
                    </span>
                  </div>
                  <Progress
                    value={result.metrics.section_coverage_score * 100}
                    className="h-2"
                  />
                </div>
              </div>
            </div>

            {/* LLM Evaluation Results */}
            {result.llm_evaluation && (
              <div className="space-y-3">
                <h4 className="text-sm font-medium">{t("detailedAnalysis")}</h4>

                {/* LLM Scores */}
                <div className="bg-muted/50 grid grid-cols-2 gap-2 rounded-lg p-3 text-sm">
                  {Object.entries(result.llm_evaluation.scores).map(
                    ([key, value]) => (
                      <div key={key} className="flex justify-between">
                        <span className="text-muted-foreground">
                          {t(`scores.${key}`)}
                        </span>
                        <span className="font-medium">{value}/10</span>
                      </div>
                    ),
                  )}
                </div>

                {/* Strengths */}
                {result.llm_evaluation.strengths.length > 0 && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 text-sm font-medium text-emerald-600">
                      <ThumbsUp className="h-4 w-4" />
                      {t("strengths")}
                    </div>
                    <ul className="space-y-1 text-sm">
                      {result.llm_evaluation.strengths
                        .slice(0, 3)
                        .map((s, i) => (
                          <li key={i} className="text-muted-foreground">
                            • {s}
                          </li>
                        ))}
                    </ul>
                  </div>
                )}

                {/* Weaknesses */}
                {result.llm_evaluation.weaknesses.length > 0 && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 text-sm font-medium text-orange-600">
                      <ThumbsDown className="h-4 w-4" />
                      {t("weaknesses")}
                    </div>
                    <ul className="space-y-1 text-sm">
                      {result.llm_evaluation.weaknesses
                        .slice(0, 3)
                        .map((w, i) => (
                          <li key={i} className="text-muted-foreground">
                            • {w}
                          </li>
                        ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Deep Evaluation Button */}
            {!result.llm_evaluation && (
              <Button
                variant="outline"
                className="w-full"
                onClick={() => runEvaluation(true)}
                disabled={deepLoading}
              >
                {deepLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {t("analyzing")}
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    {t("deepEvaluation")}
                  </>
                )}
              </Button>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
