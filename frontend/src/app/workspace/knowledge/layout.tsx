"use client";

import { DatabaseZapIcon } from "lucide-react";
import type { ReactNode } from "react";

import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { useKnowledgeBaseEnabled } from "@/core/knowledge";

export default function KnowledgeLayout({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const { enabled, isLoading } = useKnowledgeBaseEnabled();

  if (isLoading) {
    return (
      <WorkspaceContainer>
        <WorkspaceHeader />
        <WorkspaceBody>
          <div className="text-muted-foreground flex size-full items-center justify-center text-sm">
            {t.common.loading}
          </div>
        </WorkspaceBody>
      </WorkspaceContainer>
    );
  }

  if (!enabled) {
    return (
      <WorkspaceContainer>
        <WorkspaceHeader />
        <WorkspaceBody>
          <div className="flex size-full flex-col items-center justify-center gap-3 p-6 text-center">
            <div className="bg-muted flex size-14 items-center justify-center rounded-full">
              <DatabaseZapIcon className="text-muted-foreground size-7" />
            </div>
            <div>
              <p className="font-medium">{t.knowledge.featureDisabledTitle}</p>
              <p className="text-muted-foreground mt-1 max-w-md text-sm">
                {t.knowledge.featureDisabledDescription}
              </p>
            </div>
          </div>
        </WorkspaceBody>
      </WorkspaceContainer>
    );
  }

  return <>{children}</>;
}
