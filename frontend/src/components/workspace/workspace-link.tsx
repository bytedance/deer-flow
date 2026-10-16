"use client";

import Link from "next/link";
import type { ComponentProps } from "react";

import { useWorkspaceContext } from "@/core/workspaces/context";
import { workspaceHref } from "@/core/workspaces/urls";

/** Keep Next's anchors, prefetch, refs and modified-click behavior. */
export default function WorkspaceLink({
  href,
  ...props
}: ComponentProps<typeof Link>) {
  const context = useWorkspaceContext();
  return (
    <Link
      href={workspaceHref(
        href,
        context?.requestedWorkspaceId ??
          context?.state.active?.scope.workspaceId,
      )}
      {...props}
    />
  );
}
