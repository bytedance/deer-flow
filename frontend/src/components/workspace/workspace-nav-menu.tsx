"use client";

import {
  ChevronsUpDown,
  LogOutIcon,
  Settings2Icon,
  SettingsIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

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
import { useAuth } from "@/core/auth";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsDialog } from "./settings";

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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsDefaultSection, setSettingsDefaultSection] = useState<
    "appearance" | "memory" | "tools" | "skills" | "notification" | "about"
  >("appearance");
  const [mounted, setMounted] = useState(false);
  const { open: isSidebarOpen } = useSidebar();
  const { t } = useI18n();
  const { logout } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <>
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        defaultSection={settingsDefaultSection}
      />
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
                    onClick={() => {
                      setSettingsDefaultSection("appearance");
                      setSettingsOpen(true);
                    }}
                  >
                    <Settings2Icon />
                    {t.common.settings}
                  </DropdownMenuItem>
                  {/* Temporarily hidden entries in "Settings and more".
                  <a
                    href={brand.website_url ?? "https://thinktank.ai"}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <DropdownMenuItem>
                      <GlobeIcon />
                      {t.workspace.officialWebsite}
                    </DropdownMenuItem>
                  </a>
                  <a
                    href={brand.github_url ?? "https://github.com/thinktank-ai/thinktank-ai"}
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
                    href={`${brand.github_url ?? "https://github.com/thinktank-ai/thinktank-ai"}/issues`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <DropdownMenuItem>
                      <BugIcon />
                      {t.workspace.reportIssue}
                    </DropdownMenuItem>
                  </a>
                  <a href={`mailto:${brand.support_email ?? "support@thinktank.ai"}`}>
                    <DropdownMenuItem>
                      <MailIcon />
                      {t.workspace.contactUs}
                    </DropdownMenuItem>
                  </a>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => {
                    setSettingsDefaultSection("about");
                    setSettingsOpen(true);
                  }}
                >
                  <InfoIcon />
                  {t.workspace.about}
                </DropdownMenuItem>
                */}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => {
                    void logout();
                    void navigate("/login");
                  }}
                >
                  <LogOutIcon />
                  {t.workspace.signOut}
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
    </>
  );
}
