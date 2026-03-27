"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo } from "react";

import {
  BreadcrumbItem,
  BreadcrumbPage,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import {
  getSettingsSectionDefinitions,
  getWorkspaceSettingsPath,
  renderSettingsSection,
  type WorkspaceSettingsSection,
} from "./settings-sections";

export function WorkspaceSettingsShell({
  section,
}: {
  section: WorkspaceSettingsSection;
}) {
  const router = useRouter();
  const { t } = useI18n();

  const sections = useMemo(() => getSettingsSectionDefinitions(t), [t]);
  const currentSection = sections.find((item) => item.section === section);

  useEffect(() => {
    if (!currentSection) {
      return;
    }
    document.title = `${currentSection.label} - ${t.settings.title} - ${t.pages.appName}`;
  }, [currentSection, t.pages.appName, t.settings.title]);

  const handleBack = () => {
    if (window.history.length > 1) {
      router.back();
      return;
    }
    router.push("/workspace/chats/new");
  };

  if (!currentSection) {
    return null;
  }

  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <BreadcrumbItem>
          <BreadcrumbPage>{currentSection.label}</BreadcrumbPage>
        </BreadcrumbItem>
      </WorkspaceHeader>
      <WorkspaceBody>
        <div className="flex size-full flex-col">
          <div className="border-b px-4 py-3 sm:px-6">
            <Button variant="ghost" onClick={handleBack}>
              <ArrowLeftIcon className="size-4" />
              {t.settings.backToWorkspace}
            </Button>
          </div>
          <div className="grid min-h-0 flex-1 gap-6 p-4 sm:p-6 xl:grid-cols-[260px_1fr]">
            <aside className="min-h-0">
              <div className="bg-sidebar rounded-xl border p-3">
                <div className="px-2 pb-3">
                  <div className="text-base font-semibold">{t.settings.title}</div>
                  <div className="text-muted-foreground mt-1 text-sm">
                    {t.settings.description}
                  </div>
                </div>
                <nav className="space-y-1">
                  {sections.map(({ section: itemSection, icon: Icon, label }) => {
                    const active = itemSection === section;
                    return (
                      <Link
                        key={itemSection}
                        href={getWorkspaceSettingsPath(itemSection)}
                        className={cn(
                          "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                          active
                            ? "bg-primary text-primary-foreground shadow-sm"
                            : "text-muted-foreground hover:bg-muted hover:text-foreground",
                        )}
                      >
                        <Icon className="size-4" />
                        <span>{label}</span>
                      </Link>
                    );
                  })}
                </nav>
              </div>
            </aside>
            <ScrollArea className="min-h-0 rounded-xl border">
              <div className="p-4 sm:p-6">{renderSettingsSection(section)}</div>
            </ScrollArea>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
