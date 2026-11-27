"use client";

import { Check, ChevronDown, Languages } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { setLocaleInCookie } from "@/core/i18n/cookies";
import {
  getLandingDocsLang,
  type LandingLocale,
  useOptionalLandingLocale,
} from "@/core/i18n/landing";
import { cn } from "@/lib/utils";

const LANGUAGE_OPTIONS: ReadonlyArray<{
  locale: LandingLocale;
  label: string;
  shortLabel: string;
}> = [
  { locale: "en-US", label: "English", shortLabel: "EN" },
  { locale: "zh-CN", label: "简体中文", shortLabel: "中文" },
];

const DOCS_PATH_PATTERN = /^\/(en|zh)(\/docs(?:\/.*)?)$/;

export type LanguageSwitchProps = {
  className?: string;
  locale?: LandingLocale;
};

export function LanguageSwitch({ className, locale }: LanguageSwitchProps) {
  const { locale: activeLocale, setLocale } = useOptionalLandingLocale(locale);
  const pathname = usePathname();
  const router = useRouter();

  const currentShortLabel = activeLocale === "zh-CN" ? "中文" : "EN";
  const triggerAriaLabel =
    activeLocale === "zh-CN" ? "切换语言" : "Switch language";

  const handleSelect = (nextLocale: LandingLocale) => {
    setLocaleInCookie(nextLocale);

    const docsMatch = pathname ? DOCS_PATH_PATTERN.exec(pathname) : null;
    if (docsMatch) {
      const nextDocsLang = getLandingDocsLang(nextLocale);
      const restPath = docsMatch[2] ?? "/docs";
      if (docsMatch[1] !== nextDocsLang) {
        const search =
          typeof window !== "undefined" ? window.location.search : "";
        const hash = typeof window !== "undefined" ? window.location.hash : "";
        router.push(`/${nextDocsLang}${restPath}${search}${hash}`);
        return;
      }
    }

    if (setLocale) {
      setLocale(nextLocale);
      return;
    }

    if (nextLocale !== activeLocale) {
      router.refresh();
    }
  };

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={triggerAriaLabel}
          className={cn(
            "focus-visible:ring-ring/50 inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium text-[var(--df-muted-fg)] transition-colors duration-150 hover:bg-[var(--df-muted)] hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none data-[state=open]:bg-[var(--df-muted)] data-[state=open]:text-[var(--df-ink)]",
            className,
          )}
        >
          <Languages className="size-3.5" aria-hidden="true" />
          <span>{currentShortLabel}</span>
          <ChevronDown className="size-3 opacity-70" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        sideOffset={8}
        className="w-44 rounded-xl border border-[var(--df-border)] bg-[var(--df-panel)] p-1.5 text-[var(--df-ink)] shadow-[0_14px_38px_var(--df-shadow)]"
      >
        {LANGUAGE_OPTIONS.map((option) => {
          const isActive = option.locale === activeLocale;
          return (
            <DropdownMenuItem
              key={option.locale}
              onSelect={() => handleSelect(option.locale)}
              className={cn(
                "flex items-center justify-between rounded-lg px-2.5 py-2 text-sm text-[var(--df-ink)] transition-colors focus:bg-[var(--df-muted)] focus:text-[var(--df-ink)]",
                isActive && "bg-[var(--df-accent-soft)] font-medium",
              )}
            >
              <span className="flex items-center gap-2">
                <span>{option.label}</span>
                <span className="font-mono text-[10px] text-[var(--df-muted-fg)]">
                  {option.shortLabel}
                </span>
              </span>
              {isActive && (
                <Check
                  className="size-3.5 text-[var(--df-accent)]"
                  aria-hidden="true"
                />
              )}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
