"use client";

import {
  ChevronsUpDown,
  InfoIcon,
  Settings2Icon,
  UserCircleIcon,
} from "lucide-react";
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
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsDialog } from "./settings";

/**
 * Render the user's identity label for the sidebar footer.
 *
 * The backend stores administrators with synthetic `user@unknown` emails;
 * showing the raw value to operators is confusing and looks like a bug.
 * Strip the placeholder domain and fall back to the local-part — or to a
 * generic label if even that is missing.
 */
function formatUserLabel(
  email: string | null | undefined,
  fallback: string,
): string {
  if (!email) return fallback;
  const trimmed = email.trim();
  if (!trimmed) return fallback;
  const placeholderDomains = ["unknown", "example.com", "localhost"];
  const [local, domain] = trimmed.split("@");
  if (domain && placeholderDomains.includes(domain.toLowerCase())) {
    return local || fallback;
  }
  return trimmed;
}

function NavMenuButtonContent({
  isSidebarOpen,
  userName,
}: {
  isSidebarOpen: boolean;
  userName: string;
}) {
  return isSidebarOpen ? (
    <div className="text-foreground flex w-full items-center gap-2 text-left text-sm">
      <UserCircleIcon className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate font-medium">{userName}</span>
      <ChevronsUpDown className="text-muted-foreground ml-auto size-4 shrink-0" />
    </div>
  ) : (
    <div className="flex size-full items-center justify-center">
      <UserCircleIcon className="text-muted-foreground size-4" />
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
  const { user } = useAuth();
  const displayName = user?.real_name || user?.user_name || formatUserLabel(user?.email, t.workspace.guestUser);

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
                  <NavMenuButtonContent
                    isSidebarOpen={isSidebarOpen}
                    userName={displayName}
                  />
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
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <SidebarMenuButton size="lg" className="pointer-events-none">
              <NavMenuButtonContent
                isSidebarOpen={isSidebarOpen}
                userName={displayName}
              />
            </SidebarMenuButton>
          )}
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
