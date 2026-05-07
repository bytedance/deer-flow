"use client";

import { LogOutIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/core/auth/AuthProvider";
import { isSystemAdminView } from "@/core/admin/scope";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export function AdminSidebar() {
  const pathname = usePathname();
  const { t } = useI18n();
  const { user, logout } = useAuth();
  const isSystemAdmin = isSystemAdminView(user);

  const links = [
    { href: "/admin", label: t.admin.dashboard },
    { href: "/admin/tenants", label: t.admin.tenants },
    { href: "/admin/usage", label: t.admin.usage },
    { href: "/admin/logs", label: t.admin.logs },
  ];

  return (
    <aside className="flex w-56 flex-col gap-1 border-r bg-muted/30 p-4">
      <h2 className="mb-4 text-lg font-semibold tracking-tight">Admin</h2>
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className={cn(
            "rounded-md px-3 py-2 text-sm transition-colors hover:bg-muted",
            pathname === link.href && "bg-muted font-medium",
          )}
        >
          {link.label}
        </Link>
      ))}
      {user && (
        <div className="mt-auto border-t pt-4">
          <div className="mb-3 min-w-0">
            <p className="truncate text-sm font-medium">{user.email}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t.admin.currentTenant}: {user.tenant_id}
            </p>
            <div className="mt-1 flex items-center gap-1.5">
              <span className="shrink-0 rounded bg-blue-100 px-1 py-px text-[10px] font-medium text-blue-700 dark:bg-blue-900 dark:text-blue-200">
                {user.system_role}
              </span>
              <span className="shrink-0 rounded bg-emerald-100 px-1 py-px text-[10px] font-medium text-emerald-700 dark:bg-emerald-900 dark:text-emerald-200">
                {isSystemAdmin ? t.admin.globalScope : t.admin.tenantScope}
              </span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void logout()}
            className="w-full justify-start gap-2 px-2"
          >
            <LogOutIcon className="size-4" />
            {t.settings.account.signOut}
          </Button>
        </div>
      )}
    </aside>
  );
}
