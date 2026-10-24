"use client";

import { useRouter } from "next/navigation";
import { useMemo } from "react";

import { useWorkspaceContext } from "./context";
import { workspaceHref } from "./urls";

/** Native navigation with a captured locator; it never changes a request scope. */
export function useWorkspaceRouter() {
  const router = useRouter();
  const context = useWorkspaceContext();
  const selector =
    context?.requestedWorkspaceId ?? context?.state.active?.scope.workspaceId;
  const signal = context?.state.active?.scope.signal;
  return useMemo(
    () => ({
      ...router,
      push: (
        href: string,
        ...options: Parameters<typeof router.push> extends [
          string,
          ...infer Rest,
        ]
          ? Rest
          : never
      ) => {
        if (!signal?.aborted)
          router.push(workspaceHref(href, selector), ...options);
      },
      replace: (
        href: string,
        ...options: Parameters<typeof router.replace> extends [
          string,
          ...infer Rest,
        ]
          ? Rest
          : never
      ) => {
        if (!signal?.aborted)
          router.replace(workspaceHref(href, selector), ...options);
      },
      prefetch: (
        href: string,
        ...options: Parameters<typeof router.prefetch> extends [
          string,
          ...infer Rest,
        ]
          ? Rest
          : never
      ) => {
        if (!signal?.aborted)
          router.prefetch(workspaceHref(href, selector), ...options);
      },
      // Preserve the native no-remount contract when a streamed new chat gets its ID.
      replaceHistory: (href: string, state: unknown = null) => {
        if (!signal?.aborted)
          window.history.replaceState(state, "", workspaceHref(href, selector));
      },
    }),
    [router, selector, signal],
  );
}
