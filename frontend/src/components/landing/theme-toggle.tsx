"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import {
  type LandingLocale,
  useOptionalLandingLocale,
} from "@/core/i18n/landing";
import { cn } from "@/lib/utils";

const emptySubscribe = () => () => {
  // No-op subscription; only used to distinguish server from hydrated client.
};

export type ThemeToggleProps = {
  className?: string;
  locale?: LandingLocale;
};

export function ThemeToggle({ className, locale }: ThemeToggleProps) {
  const { resolvedTheme, setTheme } = useTheme();
  const { locale: activeLocale } = useOptionalLandingLocale(locale);
  const mounted = useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );

  const isDark = mounted && resolvedTheme === "dark";
  const label =
    activeLocale === "zh-CN"
      ? isDark
        ? "切换至浅色主题"
        : "切换至深色主题"
      : isDark
        ? "Switch to light theme"
        : "Switch to dark theme";

  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={label}
      title={label}
      className={cn(
        "focus-visible:ring-ring/50 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[var(--df-muted-fg)] transition-colors duration-150 hover:bg-[var(--df-muted)] hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none",
        className,
      )}
    >
      {isDark ? (
        <Sun className="size-4" aria-hidden="true" />
      ) : (
        <Moon className="size-4" aria-hidden="true" />
      )}
    </button>
  );
}
