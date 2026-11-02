import { Button } from "@/components/ui/button";
import { GatewayApiError } from "@/core/api/errors";
import type { Translations } from "@/core/i18n/locales/types";

export function UsageQueryError({
  error,
  retry,
  text,
}: {
  error: Error;
  retry: () => void;
  text: Translations["usage"];
}) {
  const status = error instanceof GatewayApiError ? error.status : null;
  const message =
    status === 403
      ? text.forbidden
      : status === 404
        ? text.unavailable
        : status === 503
          ? text.databaseRequired
          : text.loadFailed;
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-xl border p-5 text-sm"
    >
      <p className="flex-1">{message}</p>
      {status !== 403 && status !== 404 && (
        <Button variant="outline" size="sm" onClick={retry}>
          {text.retry}
        </Button>
      )}
    </div>
  );
}
