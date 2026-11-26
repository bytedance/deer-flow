"use client";

import { GitHubLogoIcon } from "@radix-ui/react-icons";
import { BookOpen, MessageSquare, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  type LandingLocale,
  useOptionalLandingLocale,
} from "@/core/i18n/landing";
import { cn } from "@/lib/utils";

export const ANNOUNCEMENT_BANNER_STORAGE_KEY =
  "deerflow.landing.banner.v1.dismissed";

const BANNER_HEIGHT_VISIBLE = "105px";
const BANNER_HEIGHT_DISMISSED = "65px";

const BANNER_COPY: Record<
  LandingLocale,
  {
    text: string;
    githubLabel: string;
    quickStartLabel: string;
    discussionsLabel: string;
    dismissLabel: string;
  }
> = {
  "en-US": {
    text: "Join the DeerFlow open-source community — sandboxes, skills, memory & MCP.",
    githubLabel: "DeerFlow on GitHub",
    quickStartLabel: "Quick Start Guide",
    discussionsLabel: "GitHub Discussions",
    dismissLabel: "Dismiss announcement",
  },
  "zh-CN": {
    text: "加入 DeerFlow 开源社区 — 沙箱、技能、长期记忆与 MCP 工具一体协同。",
    githubLabel: "访问 DeerFlow GitHub 仓库",
    quickStartLabel: "快速开始文档",
    discussionsLabel: "GitHub 讨论区",
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
        "relative bg-[var(--df-cta)] text-[var(--df-cta-fg)]",
        className,
      )}
    >
      <div className="mx-auto flex max-w-[1280px] items-center justify-center gap-2.5 px-3 py-1.5 pr-10 sm:px-6 sm:pr-12">
        <p className="truncate text-xs font-medium text-white/95 sm:text-[13px]">
          {copy.text}
        </p>
        <div className="hidden shrink-0 items-center gap-1.5 sm:flex">
          <a
            href="https://github.com/bytedance/deer-flow"
            target="_blank"
            rel="noopener noreferrer"
            aria-label={copy.githubLabel}
            title={copy.githubLabel}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-white/30 text-white/95 transition-colors duration-150 hover:bg-white/20 focus-visible:ring-2 focus-visible:ring-white/80 focus-visible:outline-none"
          >
            <GitHubLogoIcon className="size-3.5" aria-hidden="true" />
          </a>
          <Link
            href={`/${docsLang}/docs/application/quick-start`}
            aria-label={copy.quickStartLabel}
            title={copy.quickStartLabel}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-white/30 text-white/95 transition-colors duration-150 hover:bg-white/20 focus-visible:ring-2 focus-visible:ring-white/80 focus-visible:outline-none"
          >
            <BookOpen className="size-3.5" aria-hidden="true" />
          </Link>
          <a
            href="https://github.com/bytedance/deer-flow/discussions"
            target="_blank"
            rel="noopener noreferrer"
            aria-label={copy.discussionsLabel}
            title={copy.discussionsLabel}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-white/30 text-white/95 transition-colors duration-150 hover:bg-white/20 focus-visible:ring-2 focus-visible:ring-white/80 focus-visible:outline-none"
          >
            <MessageSquare className="size-3.5" aria-hidden="true" />
          </a>
        </div>
      </div>
      <button
        type="button"
        onClick={handleDismiss}
        aria-label={copy.dismissLabel}
        className="absolute top-1/2 right-2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-white/85 transition-colors duration-150 hover:bg-white/20 hover:text-white focus-visible:ring-2 focus-visible:ring-white/80 focus-visible:outline-none sm:right-4"
      >
        <X className="size-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}
