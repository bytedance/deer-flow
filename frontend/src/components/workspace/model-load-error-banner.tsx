"use client";

import { UnauthorizedError } from "@/core/api/errors";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";

export function ModelLoadErrorBanner() {
  const { t } = useI18n();
  // Observe the shared query without starting it. Model consumers remain in
  // charge of loading; this single observer only centralizes their feedback.
  const { error, isFetching, refetch } = useModels({ enabled: false });

  // The shared fetcher has already started a login redirect for this error.
  // Rendering a model-specific warning during navigation would be duplicate
  // and misleading feedback.
  if (!error || error instanceof UnauthorizedError) {
    return null;
  }

  return (
    <div
      role="alert"
      className="border-destructive/20 bg-destructive/10 text-destructive flex items-center justify-between gap-3 border-b px-4 py-2 text-sm"
    >
      <span className="min-w-0">
        {t.workspace.modelLoadFailed}{" "}
        <span className="opacity-80">{error.message}</span>
      </span>
      <button
        type="button"
        disabled={isFetching}
        aria-busy={isFetching}
        onClick={() => {
          void refetch();
        }}
        className="border-destructive/30 hover:bg-destructive/10 shrink-0 cursor-pointer rounded-md border bg-transparent px-3 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isFetching
          ? t.workspace.modelLoadRetrying
          : t.workspace.modelLoadRetry}
      </button>
    </div>
  );
}
