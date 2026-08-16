"use client";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
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
    <Alert
      variant="destructive"
      className="border-destructive/20 bg-destructive/10 rounded-none border-x-0 border-t-0 px-4 py-2"
    >
      <AlertDescription className="text-destructive flex w-full items-center justify-between gap-3">
        <span className="min-w-0">{t.workspace.modelLoadFailed}</span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isFetching}
          aria-busy={isFetching}
          onClick={() => {
            void refetch();
          }}
          className="border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive dark:hover:bg-destructive/10 h-7 bg-transparent px-3 text-xs shadow-none dark:bg-transparent"
        >
          {isFetching
            ? t.workspace.modelLoadRetrying
            : t.workspace.modelLoadRetry}
        </Button>
      </AlertDescription>
    </Alert>
  );
}
