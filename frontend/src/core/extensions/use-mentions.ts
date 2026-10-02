"use client";

import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

import { useFrontendExtensions } from "./hooks";
import { searchExtensionMentions } from "./mentions";

const empty = { items: [], failed: false };
export function useExtensionMentions(query: string, threadId: string) {
  const { user } = useAuth();
  const { locale } = useI18n();
  const extensions = useFrontendExtensions();
  const [attempt, retry] = useState(0);
  const scope = useMemo(
    () => ({
      userId: user?.id,
      locale,
      threadId,
      entries: extensions.data,
    }),
    [user?.id, locale, threadId, extensions.data],
  );
  const request = useMemo(
    () => ({ scope, query, attempt }),
    [scope, query, attempt],
  );
  const [state, setState] = useState<{
    request: typeof request;
    result: Awaited<ReturnType<typeof searchExtensionMentions>>;
  }>();
  useEffect(() => {
    const abort = new AbortController();
    const timer = setTimeout(() => {
      void searchExtensionMentions(
        (scope.entries ?? []).filter(
          (entry) => entry.viewer_id === scope.userId,
        ),
        request.query,
        {
          locale: scope.locale,
          threadId: scope.threadId,
          signal: abort.signal,
        },
      )
        .then((result) => {
          if (!abort.signal.aborted) setState({ request, result });
        })
        .catch(() => {
          /* Unmount, account, thread, or query change. */
        });
    }, 150);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [scope, request]);
  // Keep settled suggestions during query/retry refreshes, but never across
  // viewer, thread, locale or installed-snapshot changes.
  const result = state?.request.scope === scope ? state.result : undefined;
  return {
    ...(result ?? empty),
    failed: extensions.isError || result?.failed === true,
    loading: extensions.isPending || result === undefined,
    retry: () => {
      void extensions.refetch();
      retry((value) => value + 1);
    },
  };
}
