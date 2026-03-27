import { redirect } from "next/navigation";

import { getWorkspaceSettingsPath } from "@/components/workspace/settings/settings-sections";

export default function WorkspaceSettingsIndexPage() {
  redirect(getWorkspaceSettingsPath());
}
