"use client";

import {
  InfoIcon,
  BrainIcon,
  SettingsIcon,
  SparklesIcon,
  UserIcon,
  WrenchIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const SETTINGS_ROOT = "/workspace/settings";

export function SettingsShell({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const pathname = usePathname();

  const sections = useMemo(
    () => [
      {
        id: "general",
        href: `${SETTINGS_ROOT}/general`,
        label: t.settings.sections.general,
        icon: SettingsIcon,
      },
      {
        id: "account",
        href: `${SETTINGS_ROOT}/account`,
        label: t.settings.sections.account,
        icon: UserIcon,
      },
      {
        id: "memory",
        href: `${SETTINGS_ROOT}/memory`,
        label: t.settings.sections.memory,
        icon: BrainIcon,
      },
      {
        id: "tools",
        href: `${SETTINGS_ROOT}/tools`,
        label: t.settings.sections.tools,
        icon: WrenchIcon,
      },
      {
        id: "skills",
        href: `${SETTINGS_ROOT}/skills`,
        label: t.settings.sections.skills,
        icon: SparklesIcon,
      },
      {
        id: "about",
        href: `${SETTINGS_ROOT}/about`,
        label: t.settings.sections.about,
        icon: InfoIcon,
      },
    ],
    [
      t.settings.sections.general,
      t.settings.sections.account,
      t.settings.sections.memory,
      t.settings.sections.tools,
      t.settings.sections.skills,
      t.settings.sections.about,
    ],
  );

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
          {/* Page header */}
          <header className="mb-8 space-y-1.5">
            <h1 className="text-base font-semibold tracking-tight">
              {t.settings.title}
            </h1>
            <p className="text-muted-foreground text-sm">
              {t.settings.description}
            </p>
          </header>

          {/* Two-column: sticky text nav + content */}
          <div className="grid gap-8 md:grid-cols-[200px_minmax(0,1fr)] lg:gap-12">
            <nav className="self-start md:sticky md:top-8">
              <ul className="space-y-1">
                {sections.map(({ id, href, label, icon: Icon }) => {
                  const active =
                    pathname === href || pathname?.startsWith(`${href}/`);
                  return (
                    <li key={id}>
                      <Link
                        href={href}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-md px-3 py-2 text-[15px] leading-6 transition-colors",
                          active
                            ? "bg-muted text-foreground font-medium"
                            : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                        )}
                      >
                        <Icon className="size-[18px] shrink-0" />
                        <span>{label}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </nav>
            <div className="min-w-0 space-y-12 pb-10">{children}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
