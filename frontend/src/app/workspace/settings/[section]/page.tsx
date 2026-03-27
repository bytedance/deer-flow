import { notFound } from "next/navigation";

import {
  isWorkspaceSettingsSection,
} from "@/components/workspace/settings/settings-sections";
import { WorkspaceSettingsShell } from "@/components/workspace/settings/workspace-settings-shell";

export default async function WorkspaceSettingsSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  if (!isWorkspaceSettingsSection(section)) {
    notFound();
  }

  return <WorkspaceSettingsShell section={section} />;
}
