"use client";

import { useEffect } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { TrashView } from "@/components/workspace/trash/trash-view";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { isStaticWebsiteOnly } from "@/core/static-mode";

/**
 * Trash lives at ``/workspace/trash`` — deliberately NOT under
 * ``/workspace/projects/``, where the dynamic ``[id]`` segment would swallow
 * a literal ``trash`` path (spec §9).
 */
export default function TrashPage() {
  const { t } = useI18n();

  useEffect(() => {
    document.title = `${t.trash.title} - ${t.pages.appName}`;
  }, [t.trash.title, t.pages.appName]);

  // Static demo mode has no Gateway and hides every project surface.
  if (isStaticWebsiteOnly()) {
    return null;
  }

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <ScrollArea className="size-full">
          <TrashView />
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
