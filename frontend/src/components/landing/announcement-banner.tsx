"use client";

import { ArrowRight, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  type LandingLocale,
  useOptionalLandingLocale,
} from "@/core/i18n/landing";
import { cn } from "@/lib/utils";

export const ANNOUNCEMENT_BANNER_STORAGE_KEY =
  "deerflow.landing.banner.v1.dismissed";

const BANNER_HEIGHT_VISIBLE = "100px";
const BANNER_HEIGHT_DISMISSED = "64px";

const BANNER_COPY: Record<
  LandingLocale,
  {
    badge: string;
    text: string;
    ctaLabel: string;
    dismissLabel: string;
  }
> = {
  "en-US": {
    badge: "DeerFlow 2.0",
    text: "Open-source SuperAgent harness with isolated sandboxes, memory & progressive skills.",
    ctaLabel: "Read the Quick Start",
    dismissLabel: "Dismiss announcement",
  },
  "zh-CN": {
    badge: "DeerFlow 2.0",
    text: "开源超级智能体 Harness，集成隔离沙箱、长期记忆与渐进式技能系统。",
    ctaLabel: "查看快速开始",
    dismissLabel: "关闭公告",
  },
};

export type AnnouncementBannerProps = {
  className?: string;
  locale?: LandingLocale;
};

export function AnnouncementBanner({
  className,
  locale,
}: AnnouncementBannerProps) {
  const { locale: activeLocale, docsLang } = useOptionalLandingLocale(locale);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    try {
      if (
        window.localStorage.getItem(ANNOUNCEMENT_BANNER_STORAGE_KEY) === "1"
      ) {
        setDismissed(true);
      }
    } catch {
      // Ignore storage access errors in private or restricted environments.
    }
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.style.setProperty(
      "--df-header-height",
      dismissed ? BANNER_HEIGHT_DISMISSED : BANNER_HEIGHT_VISIBLE,
    );
    return () => {
      document.documentElement.style.removeProperty("--df-header-height");
    };
  }, [dismissed]);

  if (dismissed) return null;

  const copy = BANNER_COPY[activeLocale];

  const handleDismiss = () => {
    setDismissed(true);
    try {
      window.localStorage.setItem(ANNOUNCEMENT_BANNER_STORAGE_KEY, "1");
    } catch {
      // Dismissal still applies in memory if storage is unavailable.
    }
  };

  return (
    <div
      role="region"
      aria-label={copy.text}
      className={cn(
        "relative border-b border-[var(--df-border)] bg-[var(--df-bg-soft)] text-[var(--df-text-soft)]",
        className,
      )}
    >
      <div className="mx-auto flex min-h-9 max-w-[1280px] items-center justify-center gap-2 px-4 py-1.5 pr-10 text-xs sm:gap-2.5 sm:px-6 sm:pr-12">
        <span
          className="inline-block size-1.5 shrink-0 rounded-full bg-[var(--df-accent)]"
          aria-hidden="true"
        />
        <span className="hidden shrink-0 font-mono text-[11px] font-medium text-[var(--df-ink)] sm:inline">
          {copy.badge}
        </span>
        <span
          className="hidden text-[var(--df-border-strong)] sm:inline"
          aria-hidden="true"
        >
          /
        </span>
        <p className="truncate text-[12px] text-[var(--df-text-soft)] sm:text-[13px]">
          {copy.text}
        </p>
        <Link
          href={`/${docsLang}/docs/application/quick-start`}
          className="focus-visible:ring-ring/50 inline-flex shrink-0 items-center gap-1 rounded-sm text-[12px] font-medium whitespace-nowrap text-[var(--df-accent)] underline decoration-[var(--df-accent)]/40 underline-offset-4 transition-colors duration-150 hover:text-[var(--df-accent-strong)] hover:decoration-[var(--df-accent-strong)] focus-visible:ring-2 focus-visible:outline-none sm:text-[13px]"
        >
          <span>{copy.ctaLabel}</span>
          <ArrowRight className="size-3" aria-hidden="true" />
        </Link>
      </div>
      <button
        type="button"
        onClick={handleDismiss}
        aria-label={copy.dismissLabel}
        className="focus-visible:ring-ring/50 absolute top-1/2 right-2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full text-[var(--df-muted-fg)] transition-colors duration-150 hover:bg-[var(--df-muted-2)] hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none sm:right-4"
      >
        <X className="size-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}
