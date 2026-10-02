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
      query,
      entries: extensions.data,
      attempt,
    }),
    [user?.id, locale, threadId, query, extensions.data, attempt],
  );
  const [state, setState] = useState<{
    scope: typeof scope;
    result: Awaited<ReturnType<typeof searchExtensionMentions>>;
  }>();
  useEffect(() => {
    const abort = new AbortController();
    const timer = setTimeout(() => {
      void searchExtensionMentions(
        (scope.entries ?? []).filter(
          (entry) => entry.viewer_id === scope.userId,
        ),
        scope.query,
        {
          locale: scope.locale,
          threadId: scope.threadId,
          signal: abort.signal,
        },
      )
        .then((result) => {
          if (!abort.signal.aborted) setState({ scope, result });
        })
        .catch(() => {
          /* Unmount, account, thread, or query change. */
        });
    }, 150);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [scope]);
  return {
    ...(state?.scope === scope ? state.result : empty),
    failed:
      extensions.isError || (state?.scope === scope && state.result.failed),
    loading: extensions.isPending || state?.scope !== scope,
    retry: () => {
      void extensions.refetch();
      retry((value) => value + 1);
    },
  };
}
