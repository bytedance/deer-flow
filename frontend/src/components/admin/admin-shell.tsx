"use client";

import {
  ActivityIcon,
  BadgeDollarSignIcon,
  BookOpenCheckIcon,
  LayoutDashboardIcon,
  ReceiptTextIcon,
  ShieldAlertIcon,
  UsersRoundIcon,
  WrenchIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const navigation = [
  { href: "/workspace/admin", label: "运营概览", icon: LayoutDashboardIcon },
  {
    href: "/workspace/admin/tenants",
    label: "租户与用户",
    icon: UsersRoundIcon,
  },
  {
    href: "/workspace/admin/billing",
    label: "计费与模型",
    icon: BadgeDollarSignIcon,
  },
  { href: "/workspace/admin/usage", label: "用量账单", icon: ActivityIcon },
  { href: "/workspace/admin/orders", label: "充值订单", icon: ReceiptTextIcon },
  { href: "/workspace/admin/skills", label: "技能市场", icon: WrenchIcon },
  { href: "/workspace/admin/safety", label: "内容安全", icon: ShieldAlertIcon },
  {
    href: "/workspace/admin/audit",
    label: "审计日志",
    icon: BookOpenCheckIcon,
  },
] as const;

export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  return (
    <div className="bg-muted/30 text-foreground min-h-svh">
      <aside className="bg-background fixed inset-y-0 left-0 z-20 hidden w-60 border-r px-3 py-5 md:flex md:flex-col">
        <Link
          className="px-3 text-base font-semibold tracking-tight"
          href="/workspace/admin"
        >
          DeerFlow{" "}
          <span className="text-muted-foreground font-normal">运营</span>
        </Link>
        <nav aria-label="运营后台导航" className="mt-8 space-y-1">
          {navigation.map(({ href, label, icon: Icon }) => {
            const active =
              href === "/workspace/admin"
                ? pathname === href
                : pathname.startsWith(href);
            return (
              <Link
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
                href={href}
                key={href}
              >
                <Icon className="size-4" />
                {label}
              </Link>
            );
          })}
        </nav>
        <p className="text-muted-foreground mt-auto px-3 text-xs">
          平台管理员控制台
        </p>
      </aside>
      <div className="md:pl-60">
        <header className="bg-background flex h-16 items-center justify-between border-b px-5 md:px-8">
          <span className="text-sm font-medium">多租户运营后台</span>
          <Link
            className="text-muted-foreground hover:text-foreground text-sm"
            href="/login"
          >
            退出登录
          </Link>
        </header>
        <main className="mx-auto w-full max-w-7xl px-5 py-8 md:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}
