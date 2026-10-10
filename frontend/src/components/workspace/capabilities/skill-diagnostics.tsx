"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangleIcon, RefreshCwIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { loadSkillDiagnostics, reloadSkills } from "@/core/skills/api";

export function SkillDiagnostics({ userId }: { userId: string }) {
  const { t } = useI18n();
  const text = t.settings.skills;
  const client = useQueryClient();
  const queryKey = ["skill-diagnostics", userId];
  const diagnostics = useQuery({
    queryKey,
    queryFn: ({ signal }) => loadSkillDiagnostics(signal),
    retry: false,
  });
  const reload = useMutation({
    mutationFn: reloadSkills,
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["skills"] }),
        client.invalidateQueries({ queryKey }),
      ]);
    },
  });
  const failures = diagnostics.data ?? [];
  return (
    <div className="mb-4 space-y-3">
      <div className="flex justify-end">
        <Button
          size="sm"
          variant="outline"
          disabled={reload.isPending || diagnostics.isFetching}
          onClick={() => reload.mutate()}
        >
          <RefreshCwIcon
            className={reload.isPending ? "size-4 animate-spin" : "size-4"}
          />
          {reload.isPending
            ? text.diagnosticsRefreshing
            : text.diagnosticsRefresh}
        </Button>
      </div>
      <p className="text-muted-foreground text-sm">{text.diagnosticsScope}</p>
      {(diagnostics.isError || reload.isError) && (
        <p role="alert" className="text-destructive text-sm">
          {reload.isError
            ? text.diagnosticsReloadFailed
            : text.diagnosticsFailed}
        </p>
      )}
      {failures.length > 0 && (
        <section
          aria-label={text.diagnosticsTitle}
          className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4"
        >
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <AlertTriangleIcon className="size-4 text-amber-600" />
            {text.diagnosticsTitle}
          </h3>
          <ul className="mt-3 space-y-3">
            {failures.map((failure) => (
              <li
                key={`${failure.package}/${failure.path}`}
                className="text-sm"
              >
                <code className="break-all">{`${failure.package}/${failure.path}${failure.line == null ? "" : `:${failure.line}${failure.column == null ? "" : `:${failure.column}`}`}`}</code>
                <p className="mt-1">{text.diagnosticsInvalid}</p>
                {failure.hint === "quote_colon_value" && (
                  <p className="text-muted-foreground">
                    {text.diagnosticsQuote}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
