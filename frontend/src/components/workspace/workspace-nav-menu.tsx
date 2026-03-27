"use client";

import {
  BugIcon,
  ChevronsUpDown,
  GlobeIcon,
  InfoIcon,
  MailIcon,
  Settings2Icon,
  SettingsIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";

import { GithubIcon } from "./github-icon";
import { getWorkspaceSettingsPath } from "./settings/settings-sections";

function NavMenuButtonContent({
  isSidebarOpen,
  t,
}: {
  isSidebarOpen: boolean;
  t: ReturnType<typeof useI18n>["t"];
}) {
  return isSidebarOpen ? (
    <div className="text-muted-foreground flex w-full items-center gap-2 text-left text-sm">
      <SettingsIcon className="size-4" />
      <span>{t.workspace.settingsAndMore}</span>
      <ChevronsUpDown className="text-muted-foreground ml-auto size-4" />
    </div>
  ) : (
    <div className="flex size-full items-center justify-center">
      <SettingsIcon className="text-muted-foreground size-4" />
    </div>
  );
}

export function WorkspaceNavMenu() {
  const [mounted, setMounted] = useState(false);
  const { open: isSidebarOpen } = useSidebar();
  const { t } = useI18n();
  const router = useRouter();

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <SidebarMenu className="w-full">
      <SidebarMenuItem>
        {mounted ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <SidebarMenuButton
                size="lg"
                className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
              >
                <NavMenuButtonContent isSidebarOpen={isSidebarOpen} t={t} />
              </SidebarMenuButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
              align="end"
              sideOffset={4}
            >
              <DropdownMenuGroup>
                <DropdownMenuItem
                  onClick={() => router.push(getWorkspaceSettingsPath())}
                >
                  <Settings2Icon />
                  {t.common.settings}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <a
                  href="https://deerflow.tech/"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <DropdownMenuItem>
                    <GlobeIcon />
                    {t.workspace.officialWebsite}
                  </DropdownMenuItem>
                </a>
                <a
                  href="https://github.com/bytedance/deer-flow"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <DropdownMenuItem>
                    <GithubIcon />
                    {t.workspace.visitGithub}
                  </DropdownMenuItem>
                </a>
                <DropdownMenuSeparator />
                <a
                  href="https://github.com/bytedance/deer-flow/issues"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <DropdownMenuItem>
                    <BugIcon />
                    {t.workspace.reportIssue}
                  </DropdownMenuItem>
                </a>
                <a href="mailto:support@deerflow.tech">
                  <DropdownMenuItem>
                    <MailIcon />
                    {t.workspace.contactUs}
                  </DropdownMenuItem>
                </a>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => router.push(getWorkspaceSettingsPath("about"))}
              >
                <InfoIcon />
                {t.workspace.about}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <SidebarMenuButton size="lg" className="pointer-events-none">
            <NavMenuButtonContent isSidebarOpen={isSidebarOpen} t={t} />
          </SidebarMenuButton>
        )}
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
