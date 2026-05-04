"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export function AdminSidebar() {
  const pathname = usePathname();
  const { t } = useI18n();

  const links = [
    { href: "/admin", label: t.admin.dashboard },
    { href: "/admin/tenants", label: t.admin.tenants },
    { href: "/admin/usage", label: t.admin.usage },
    { href: "/admin/logs", label: t.admin.logs },
  ];

  return (
    <aside className="w-56 border-r bg-muted/30 p-4 flex flex-col gap-1">
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
    </aside>
  );
}
