"use client";

import { useEffect } from "react";

import { UsageDashboard } from "@/components/workspace/usage/usage-dashboard";
import {
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

export default function UsagePage() {
  const { t } = useI18n();
  useEffect(() => {
    document.title = `${t.usage.title} - ${t.pages.appName}`;
  }, [t.usage.title, t.pages.appName]);
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <main className="min-h-0 flex-1 overflow-y-auto">
        <UsageDashboard />
      </main>
    </WorkspaceContainer>
  );
}
