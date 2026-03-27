import {
  BellIcon,
  BoxesIcon,
  BrainIcon,
  InfoIcon,
  PaletteIcon,
  SparklesIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";

import { AboutSettingsPage } from "@/components/workspace/settings/about-settings-page";
import { AppearanceSettingsPage } from "@/components/workspace/settings/appearance-settings-page";
import { MemorySettingsPage } from "@/components/workspace/settings/memory-settings-page";
import { ModelServicesSettingsPage } from "@/components/workspace/settings/model-services-settings-page";
import { NotificationSettingsPage } from "@/components/workspace/settings/notification-settings-page";
import { SkillSettingsPage } from "@/components/workspace/settings/skill-settings-page";
import { ToolSettingsPage } from "@/components/workspace/settings/tool-settings-page";
import type { Translations } from "@/core/i18n/locales/types";

export type WorkspaceSettingsSection =
  | "model-services"
  | "appearance"
  | "notification"
  | "memory"
  | "tools"
  | "skills"
  | "about";

export type DialogSettingsSection =
  | "modelServices"
  | "appearance"
  | "notification"
  | "memory"
  | "tools"
  | "skills"
  | "about";

type SettingsSectionDefinition = {
  section: WorkspaceSettingsSection;
  dialogSection: DialogSettingsSection;
  icon: LucideIcon;
  label: string;
};

export const defaultWorkspaceSettingsSection: WorkspaceSettingsSection =
  "model-services";

export function isWorkspaceSettingsSection(
  value: string,
): value is WorkspaceSettingsSection {
  return [
    "model-services",
    "appearance",
    "notification",
    "memory",
    "tools",
    "skills",
    "about",
  ].includes(value);
}

export function getWorkspaceSettingsPath(
  section: WorkspaceSettingsSection = defaultWorkspaceSettingsSection,
) {
  return `/workspace/settings/${section}`;
}

export function getSettingsSectionDefinitions(
  t: Translations,
): SettingsSectionDefinition[] {
  return [
    {
      section: "model-services",
      dialogSection: "modelServices",
      label: t.settings.sections.modelServices,
      icon: BoxesIcon,
    },
    {
      section: "appearance",
      dialogSection: "appearance",
      label: t.settings.sections.appearance,
      icon: PaletteIcon,
    },
    {
      section: "notification",
      dialogSection: "notification",
      label: t.settings.sections.notification,
      icon: BellIcon,
    },
    {
      section: "memory",
      dialogSection: "memory",
      label: t.settings.sections.memory,
      icon: BrainIcon,
    },
    {
      section: "tools",
      dialogSection: "tools",
      label: t.settings.sections.tools,
      icon: WrenchIcon,
    },
    {
      section: "skills",
      dialogSection: "skills",
      label: t.settings.sections.skills,
      icon: SparklesIcon,
    },
    {
      section: "about",
      dialogSection: "about",
      label: t.settings.sections.about,
      icon: InfoIcon,
    },
  ];
}

export function renderSettingsSection(section: WorkspaceSettingsSection) {
  switch (section) {
    case "model-services":
      return <ModelServicesSettingsPage />;
    case "appearance":
      return <AppearanceSettingsPage />;
    case "notification":
      return <NotificationSettingsPage />;
    case "memory":
      return <MemorySettingsPage />;
    case "tools":
      return <ToolSettingsPage />;
    case "skills":
      return <SkillSettingsPage />;
    case "about":
      return <AboutSettingsPage />;
    default:
      return null;
  }
}
