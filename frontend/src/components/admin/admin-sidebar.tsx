"use client";

import {
  ClipboardListIcon,
  GaugeIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  type LucideIcon,
  SparklesIcon,
  UsersIcon,
} from "@/components/ui/icons";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/ui/button";
import { isSystemAdminView } from "@/core/admin/scope";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export function AdminSidebar() {
  const pathname = usePathname();
  const { t } = useI18n();
  const { user, logout } = useAuth();
  const isSystemAdmin = isSystemAdminView(user);

  const links: { href: string; label: string; icon: LucideIcon }[] = [
    { href: "/admin", label: t.admin.dashboard, icon: LayoutDashboardIcon },
    { href: "/admin/tenants", label: t.admin.tenants, icon: UsersIcon },
    { href: "/admin/usage", label: t.admin.usage, icon: GaugeIcon },
    { href: "/admin/logs", label: t.admin.logs, icon: ClipboardListIcon },
    { href: "/admin/skills", label: "Skills", icon: SparklesIcon },
  ];

  return (
    <aside className="bg-sidebar text-sidebar-foreground flex w-56 shrink-0 flex-col border-r">
      {/* Brand mark — same lockup as the workspace + auth pages */}
      <div className="border-sidebar-border/60 flex h-14 items-center gap-2 border-b px-4">
        <span
          aria-hidden="true"
          className="bg-primary text-primary-foreground inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-[11px] font-bold tracking-tight"
        >
          E
        </span>
        <span className="text-foreground truncate text-sm font-semibold tracking-tight">
          {t.admin.title}
        </span>
      </div>

      <nav className="flex flex-col gap-0.5 p-2">
        {links.map((link) => {
          const Icon = link.icon;
          const active = pathname === link.href;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "group relative flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
              )}
              aria-current={active ? "page" : undefined}
            >
              {active && (
                <span
                  aria-hidden="true"
                  className="bg-primary absolute top-1 bottom-1 left-0 w-0.5 rounded-r"
                />
              )}
              <Icon className="size-4 shrink-0" />
              <span className="truncate">{link.label}</span>
            </Link>
          );
        })}
      </nav>

      {user && (
        <div className="border-sidebar-border/60 mt-auto border-t p-3">
          <div className="mb-2 min-w-0">
            <p className="text-foreground truncate text-sm font-medium">
              {user.real_name || user.user_name || user.email}
            </p>
            <p className="text-muted-foreground mt-0.5 truncate text-xs">
              {t.admin.currentTenant}: {user.tenant_id}
            </p>
            <div className="mt-1.5 flex items-center gap-1.5">
              <span className="bg-primary/15 text-primary border-primary/20 inline-flex shrink-0 items-center rounded border px-1.5 py-px text-[10px] font-medium">
                {user.system_role}
              </span>
              <span className="bg-muted text-muted-foreground border-border/60 inline-flex shrink-0 items-center rounded border px-1.5 py-px text-[10px] font-medium">
                {isSystemAdmin ? t.admin.globalScope : t.admin.tenantScope}
              </span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void logout()}
            className="text-muted-foreground hover:text-foreground w-full justify-start gap-2 px-2"
          >
            <LogOutIcon className="size-4" />
            {t.settings.account.signOut}
          </Button>
        </div>
      )}
    </aside>
  );
}
