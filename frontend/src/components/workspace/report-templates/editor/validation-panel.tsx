"use client";

import { AlertCircle, AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { validateReportTemplate } from "@/core/report-templates/api";
import type { ValidationIssue } from "@/core/report-templates/types";
import type { ReportTemplateDSL } from "@/core/report-templates/use-template-dsl";

interface ValidationPanelProps {
  templateId: string;
  dsl: ReportTemplateDSL;
}

export function ValidationPanel({ templateId, dsl }: ValidationPanelProps) {
  const { t } = useI18n();
  const [errors, setErrors] = useState<ValidationIssue[]>([]);
  const [warnings, setWarnings] = useState<ValidationIssue[]>([]);
  const [isValidating, setIsValidating] = useState(false);
  const [lastValidated, setLastValidated] = useState<Date | null>(null);

  const validate = useCallback(async () => {
    setIsValidating(true);
    try {
      const result = await validateReportTemplate(
        templateId,
        dsl as unknown as Record<string, unknown>,
      );
      setErrors(result.errors);
      setWarnings(result.warnings);
      setLastValidated(new Date());
    } catch {
      // Ignore when the validation endpoint is unavailable.
    } finally {
      setIsValidating(false);
    }
  }, [dsl, templateId]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void validate();
    }, 1000);
    return () => clearTimeout(timer);
  }, [validate]);

  if (isValidating) {
    return (
      <div className="flex items-center gap-2 border-t px-3 py-1.5 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        {t.editor.validating}
      </div>
    );
  }

  const hasIssues = errors.length > 0 || warnings.length > 0;

  if (!hasIssues && lastValidated) {
    return (
      <div className="flex items-center gap-2 border-t px-3 py-1.5 text-xs text-green-600">
        <CheckCircle2 className="h-3 w-3" />
        {t.editor.dslValid}
      </div>
    );
  }

  return (
    <div className="border-t">
      <div className="flex items-center gap-2 px-3 py-1.5">
        {errors.length > 0 && (
          <span className="flex items-center gap-1 text-xs text-destructive">
            <AlertCircle className="h-3 w-3" />
            {errors.length} {t.editor.errorCountLabel}
          </span>
        )}
        {warnings.length > 0 && (
          <span className="flex items-center gap-1 text-xs text-yellow-600">
            <AlertTriangle className="h-3 w-3" />
            {warnings.length} {t.editor.warningCountLabel}
          </span>
        )}
      </div>
      {hasIssues && (
        <div className="max-h-24 overflow-y-auto border-t px-3 py-1">
          {errors.map((error, index) => (
            <div
              key={`err-${index}`}
              className="flex items-start gap-1.5 py-0.5 text-xs"
            >
              <AlertCircle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />
              <span className="font-mono text-muted-foreground">
                {error.path}
              </span>
              <span>{error.message}</span>
            </div>
          ))}
          {warnings.map((warning, index) => (
            <div
              key={`warn-${index}`}
              className="flex items-start gap-1.5 py-0.5 text-xs"
            >
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0 text-yellow-600" />
              <span className="font-mono text-muted-foreground">
                {warning.path}
              </span>
              <span>{warning.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
