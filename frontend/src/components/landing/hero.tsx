"use client";

import { GitHubLogoIcon } from "@radix-ui/react-icons";
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  GitFork,
  Star,
  Terminal,
} from "lucide-react";
import Link from "next/link";
import { type SVGProps, useEffect, useState } from "react";

import { env } from "@/env";
import { cn } from "@/lib/utils";

import { ArchitectureDiagram } from "./architecture-diagram";

export type HeroLocale = "en-US" | "zh-CN";

export type HeroProps = {
  className?: string;
  locale?: HeroLocale;
};

type GitHubStats = {
  stars: number | null;
  forks: number | null;
};

type HeroCopy = {
  eyebrow: string;
  headline: string;
  description: string;
  partnership: string;
  starsLabel: string;
  forksLabel: string;
  getStarted: string;
  quickStart: string;
  docs: string;
  openSource: string;
};

const HERO_COPY: Record<HeroLocale, HeroCopy> = {
  "en-US": {
    eyebrow: "DEERFLOW · OPEN SOURCE",
    headline: "DeerFlow: Open-Source SuperAgent Harness.",
    description:
      "Sandboxes, persistent memory, progressive skills, MCP tools, and parallel subagents unified in one harness—built for deep research, coding, and creation tasks that span minutes to hours.",
    partnership: "In partnership with",
    starsLabel: "GitHub Stars",
    forksLabel: "Forks",
    getStarted: "Get Started",
    quickStart: "Quick Start",
    docs: "Docs",
    openSource: "Open Source",
  },
  "zh-CN": {
    eyebrow: "DEERFLOW · 开源超级智能体",
    headline: "DeerFlow：开源超级智能体引擎",
    description:
      "将隔离沙箱、长期记忆、渐进式技能、MCP 工具与并行子智能体统一在一个引擎中，稳定执行耗时数分钟至数小时的深度研究、编程与创作任务。",
    partnership: "技术合作",
    starsLabel: "GitHub Stars",
    forksLabel: "Forks",
    getStarted: "立即开始",
    quickStart: "快速上手",
    docs: "文档",
    openSource: "开源仓库",
  },
};

function isValidCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function formatMetricCount(value: number): string {
  if (value >= 1000) {
    const truncated = Math.floor(value / 100) / 10;
    const formatted = Number.isInteger(truncated)
      ? String(truncated)
      : truncated.toFixed(1);
    return `${formatted}K+`;
  }
  return String(value);
}

export function Hero({ className, locale = "en-US" }: HeroProps) {
  const copy = HERO_COPY[locale];
  const docsLang = locale === "zh-CN" ? "zh" : "en";
  const [stats, setStats] = useState<GitHubStats>({
    stars: null,
    forks: null,
  });

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/github-stars", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok || response.status === 204) return;
        const data = (await response.json()) as {
          stars?: unknown;
          forks?: unknown;
        };
        if (controller.signal.aborted) return;
        const stars = isValidCount(data.stars) ? data.stars : null;
        const forks = isValidCount(data.forks) ? data.forks : null;
        if (stars !== null || forks !== null) {
          setStats({ stars, forks });
        }
      })
      .catch(() => {
        // Hide the optional metrics row when the endpoint is unavailable.
      });
    return () => controller.abort();
  }, []);

  const hasMetrics = stats.stars !== null || stats.forks !== null;
  const isStaticWebsite = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";

  return (
    <section
      className={cn(
        "relative flex min-h-[100svh] w-full flex-col justify-center overflow-x-clip bg-[var(--df-bg,#f6f2e8)] pt-[var(--df-header-height,105px)] text-[var(--df-ink,#171511)]",
        className,
      )}
    >
      {/* Subtle 72px editorial grid background */}
      <div
        aria-hidden="true"
        className="landing-grid-bg pointer-events-none absolute inset-0 z-0"
        style={{
          backgroundImage:
            "linear-gradient(90deg, var(--df-grid, rgba(35, 31, 25, 0.055)) 1px, transparent 1px), linear-gradient(var(--df-grid-soft, rgba(35, 31, 25, 0.045)) 1px, transparent 1px)",
          backgroundSize: "72px 72px",
        }}
      />
      {/* Soft vignette beneath the sticky header */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 z-0 h-40 bg-gradient-to-b from-[var(--df-bg,#f6f2e8)] to-transparent"
      />

      <div className="relative z-10 mx-auto w-full max-w-[1520px] px-4 py-10 sm:px-10 sm:py-14 lg:px-14 xl:px-20 2xl:px-24">
        <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(460px,540px)] lg:gap-10 xl:grid-cols-[minmax(0,1fr)_560px] xl:gap-16">
          {/* Left column: editorial copy, live metrics, entry-point CTAs */}
          <div className="flex min-w-0 flex-col items-center text-center lg:items-start lg:text-left">
            <p className="font-mono text-xs font-medium tracking-[0.26em] text-[var(--df-accent,#0a7c93)] uppercase">
              {copy.eyebrow}
            </p>

            <h1 className="mt-4 font-serif text-[2.25rem] leading-[1.02] font-semibold tracking-normal text-balance text-[var(--df-ink,#171511)] sm:text-[3.1rem] lg:text-[3.4rem] xl:text-[3.85rem]">
              {copy.headline}
            </h1>

            <p className="mt-5 max-w-xl text-sm leading-6 text-[var(--df-muted-fg,#625b50)] sm:text-base sm:leading-7">
              {copy.description}
            </p>

            {isStaticWebsite && (
              <a
                href="https://byteplus.com"
                target="_blank"
                rel="noopener noreferrer"
                className="focus-visible:ring-ring/50 mt-5 inline-flex min-h-9 items-center gap-2 rounded-full border border-[var(--df-border-strong,#bdb3a2)] bg-[var(--df-panel,#fffaf1)]/85 px-3.5 py-1.5 text-xs font-medium text-[var(--df-text-soft,#3a352d)] transition-colors duration-150 hover:border-[var(--df-accent,#0a7c93)] hover:text-[var(--df-ink,#171511)] focus-visible:ring-2 focus-visible:outline-none"
              >
                <span>{copy.partnership}</span>
                <BytePlusIcon className="h-3.5 w-auto" />
                <ArrowUpRight
                  className="size-3.5 opacity-70"
                  aria-hidden="true"
                />
              </a>
            )}

            {hasMetrics && (
              <div
                data-testid="hero-github-metrics"
                className="mt-7 flex items-stretch justify-center gap-6 lg:justify-start"
              >
                {stats.stars !== null && (
                  <a
                    href="https://github.com/bytedance/deer-flow"
                    target="_blank"
                    rel="noopener noreferrer"
                    title={stats.stars.toLocaleString("en-US")}
                    className="group focus-visible:ring-ring/50 flex flex-col items-center rounded-sm focus-visible:ring-2 focus-visible:outline-none lg:items-start"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Star
                        className="size-4 text-[var(--df-accent,#0a7c93)]"
                        aria-hidden="true"
                      />
                      <span className="font-mono text-xl leading-none font-semibold text-[var(--df-ink,#171511)] tabular-nums transition-colors group-hover:text-[var(--df-accent,#0a7c93)]">
                        {formatMetricCount(stats.stars)}
                      </span>
                    </span>
                    <span className="mt-1.5 text-xs text-[var(--df-muted-fg,#625b50)]">
                      {copy.starsLabel}
                    </span>
                  </a>
                )}

                {stats.stars !== null && stats.forks !== null && (
                  <div
                    aria-hidden="true"
                    className="w-px self-stretch bg-[var(--df-border,#d8d0c2)]"
                  />
                )}

                {stats.forks !== null && (
                  <a
                    href="https://github.com/bytedance/deer-flow/forks"
                    target="_blank"
                    rel="noopener noreferrer"
                    title={stats.forks.toLocaleString("en-US")}
                    className="group focus-visible:ring-ring/50 flex flex-col items-center rounded-sm focus-visible:ring-2 focus-visible:outline-none lg:items-start"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <GitFork
                        className="size-4 text-[var(--df-accent,#0a7c93)]"
                        aria-hidden="true"
                      />
                      <span className="font-mono text-xl leading-none font-semibold text-[var(--df-ink,#171511)] tabular-nums transition-colors group-hover:text-[var(--df-accent,#0a7c93)]">
                        {formatMetricCount(stats.forks)}
                      </span>
                    </span>
                    <span className="mt-1.5 text-xs text-[var(--df-muted-fg,#625b50)]">
                      {copy.forksLabel}
                    </span>
                  </a>
                )}
              </div>
            )}

            {/* Explicit entry points: Workspace, Quick Start, Docs, Open Source */}
            <div className="mt-8 grid w-full max-w-md grid-cols-2 gap-2.5 sm:flex sm:w-auto sm:max-w-none sm:flex-wrap sm:items-center sm:justify-center sm:gap-3 lg:justify-start">
              <Link
                href="/workspace/chats/new"
                className="focus-visible:ring-ring/50 inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-[var(--df-cta,#0a7c93)] px-4 text-sm font-medium whitespace-nowrap text-[var(--df-cta-fg,#ffffff)] shadow-[0_4px_14px_-5px_color-mix(in_srgb,var(--df-cta,#0a7c93)_60%,transparent)] transition-all duration-200 hover:-translate-y-0.5 hover:bg-[var(--df-cta-hover,#086a7e)] focus-visible:ring-2 focus-visible:outline-none sm:px-5"
              >
                <span>{copy.getStarted}</span>
                <ArrowRight className="size-4 shrink-0" aria-hidden="true" />
              </Link>

              <Link
                href={`/${docsLang}/docs/application/quick-start`}
                className="focus-visible:ring-ring/50 inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-[var(--df-border-strong,#bdb3a2)] bg-transparent px-4 text-sm font-medium whitespace-nowrap text-[var(--df-ink,#171511)] transition-all duration-200 hover:-translate-y-0.5 hover:border-[var(--df-cta,#0a7c93)] hover:bg-[var(--df-cta,#0a7c93)] hover:text-[var(--df-cta-fg,#ffffff)] focus-visible:ring-2 focus-visible:outline-none sm:px-5"
              >
                <Terminal className="size-4 shrink-0" aria-hidden="true" />
                <span>{copy.quickStart}</span>
              </Link>

              <Link
                href={`/${docsLang}/docs`}
                className="focus-visible:ring-ring/50 inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-[var(--df-border-strong,#bdb3a2)] bg-transparent px-4 text-sm font-medium whitespace-nowrap text-[var(--df-ink,#171511)] transition-all duration-200 hover:-translate-y-0.5 hover:border-[var(--df-cta,#0a7c93)] hover:bg-[var(--df-cta,#0a7c93)] hover:text-[var(--df-cta-fg,#ffffff)] focus-visible:ring-2 focus-visible:outline-none sm:px-5"
              >
                <BookOpen className="size-4 shrink-0" aria-hidden="true" />
                <span>{copy.docs}</span>
              </Link>

              <a
                href="https://github.com/bytedance/deer-flow"
                target="_blank"
                rel="noopener noreferrer"
                className="focus-visible:ring-ring/50 inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-[var(--df-border-strong,#bdb3a2)] bg-transparent px-4 text-sm font-medium whitespace-nowrap text-[var(--df-ink,#171511)] transition-all duration-200 hover:-translate-y-0.5 hover:border-[var(--df-cta,#0a7c93)] hover:bg-[var(--df-cta,#0a7c93)] hover:text-[var(--df-cta-fg,#ffffff)] focus-visible:ring-2 focus-visible:outline-none sm:px-5"
              >
                <GitHubLogoIcon
                  className="size-4 shrink-0"
                  aria-hidden="true"
                />
                <span>{copy.openSource}</span>
              </a>
            </div>
          </div>

          {/* Right column: Interactive DeerFlow architecture diagram */}
          <div className="w-full min-w-0">
            <ArchitectureDiagram locale={locale} />
          </div>
        </div>
      </div>
    </section>
  );
}

function BytePlusIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={80}
      height={24}
      viewBox="0 0 120 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="BytePlus"
      {...props}
    >
      <path
        d="M30.8027 3.64648H37.9333C38.8894 3.64648 39.7259 3.81911 40.4297 4.16435C41.1334 4.50959 41.6911 4.98761 42.0762 5.59843C42.4613 6.20924 42.6472 6.88644 42.6472 7.6566C42.6472 8.34708 42.4746 8.99773 42.1426 9.58198C41.7973 10.1795 41.3326 10.631 40.7483 10.9629C41.5583 11.3082 42.1691 11.8128 42.5808 12.49C42.9924 13.1672 43.1916 13.9108 43.1916 14.734C43.1916 15.5175 42.9924 16.208 42.5941 16.8188C42.1957 17.4296 41.638 17.9209 40.921 18.2661C40.2039 18.6246 39.3408 18.7973 38.3449 18.7973H30.8027V3.64648ZM37.8005 9.99361C38.4113 9.99361 38.9026 9.82099 39.2877 9.47575C39.6728 9.13051 39.8587 8.69232 39.8587 8.1479C39.8587 7.5902 39.6728 7.12546 39.301 6.76694C38.9292 6.40842 38.4379 6.22252 37.8138 6.22252H33.5248V9.99361H37.8005ZM38.1458 16.2345C38.7831 16.2345 39.301 16.0619 39.6993 15.7034C40.0977 15.3449 40.2969 14.8934 40.2969 14.349C40.2969 13.9772 40.2039 13.6319 40.018 13.3398C39.8321 13.0477 39.5798 12.8087 39.2479 12.636C38.9292 12.4634 38.5574 12.3705 38.1325 12.3705H33.5381V16.2212H38.1458V16.2345Z"
        fill="currentColor"
      />
      <path
        d="M49.2392 18.2385L44.127 7.3236H46.7295L50.567 15.4899L54.0062 7.3236H57.6445V5.09281L60.2073 4.33594V7.3236H63.0887V9.75357H60.2073V15.304C60.2073 15.7023 60.3135 16.021 60.5259 16.2202C60.7384 16.4327 61.0438 16.5655 61.4422 16.6318C61.8405 16.6982 62.3982 16.7115 63.0887 16.6584V18.9556C61.7741 19.1016 60.7251 19.0618 59.9417 18.8626C59.1582 18.6502 58.574 18.2518 58.2022 17.6676C57.8304 17.0833 57.6445 16.2866 57.6445 15.2907V9.75357H55.5863L49.4782 24.0014H46.7959L49.2392 18.2385Z"
        fill="currentColor"
      />
      <path
        d="M70.2461 19.1147C69.1572 19.1147 68.1746 18.8491 67.2849 18.318C66.3953 17.7869 65.6782 17.0565 65.1604 16.1138C64.6425 15.1843 64.377 14.1485 64.377 13.0066C64.377 11.8912 64.6425 10.882 65.1737 9.97908C65.7048 9.06286 66.4218 8.34582 67.3248 7.82796C68.2277 7.29682 69.2236 7.03125 70.2992 7.03125C71.6536 7.03125 72.7822 7.33666 73.6719 7.93419C74.5616 8.53172 75.2122 9.36827 75.584 10.4438C75.9691 11.5194 76.0753 12.7676 75.916 14.1751L67.0061 14.1884C67.1389 14.7062 67.3779 15.1577 67.7364 15.5295C68.0949 15.9013 68.5066 16.1802 68.958 16.366C69.4095 16.5519 69.8477 16.6316 70.2461 16.6316C70.6975 16.6316 71.1092 16.5918 71.5075 16.4988C71.8926 16.4059 72.2378 16.2731 72.5432 16.0739C72.8486 15.8747 73.1142 15.649 73.3665 15.3967L73.4727 15.2639L75.5043 16.6051C74.9998 17.4416 74.296 18.0657 73.4063 18.4773C72.5167 18.9022 71.4677 19.1147 70.2461 19.1147ZM73.486 11.9576C73.3665 11.4663 73.1673 11.0281 72.8619 10.6563C72.5565 10.2845 72.1847 9.99236 71.7332 9.79318C71.2818 9.594 70.8037 9.48778 70.2992 9.48778C69.8211 9.48778 69.3564 9.594 68.8916 9.79318C68.4269 9.99236 68.0285 10.2845 67.6833 10.6563C67.3381 11.0281 67.1256 11.4663 67.0459 11.9576H73.486Z"
        fill="currentColor"
      />
      <path
        d="M78 3.64648H84.3206C86.0733 3.64648 87.4278 4.0714 88.3838 4.92122C89.3399 5.77105 89.8179 6.93956 89.8179 8.42675C89.8179 9.39608 89.6054 10.2459 89.1805 10.9762C88.7556 11.7065 88.1315 12.2642 87.3215 12.6493C86.5115 13.0344 85.5156 13.2336 84.3471 13.2336H80.7354V18.7973H78V3.64648ZM84.3737 10.7505C84.9314 10.7505 85.4227 10.6575 85.8078 10.4849C86.2061 10.3123 86.5115 10.0467 86.724 9.70149C86.9364 9.35625 87.0427 8.93133 87.0427 8.42675C87.0427 7.6566 86.8169 7.08562 86.3655 6.71382C85.914 6.34202 85.2501 6.15612 84.387 6.15612H80.7487V10.7505H84.3737Z"
        fill="currentColor"
      />
      <path
        d="M92.168 3.36719H94.8104V18.8101H92.168V3.36719Z"
        fill="currentColor"
      />
      <path
        d="M101.982 19.1155C101.158 19.1155 100.415 18.9164 99.764 18.5313C99.1134 18.1462 98.5955 17.6018 98.2237 16.9113C97.8519 16.2208 97.666 15.4507 97.666 14.6008V7.32422H100.282V13.6979C100.282 14.2822 100.375 14.7735 100.574 15.1984C100.773 15.6233 101.052 15.9553 101.424 16.1943C101.796 16.4333 102.247 16.5528 102.765 16.5528C103.256 16.5528 103.708 16.4333 104.106 16.181C104.504 15.942 104.836 15.5835 105.075 15.1187C105.314 14.654 105.434 14.1228 105.434 13.512V7.32422H108.076V18.8101H105.527V17.3628C105.155 17.947 104.651 18.3719 104.04 18.6774C103.442 18.9562 102.752 19.1155 101.982 19.1155Z"
        fill="currentColor"
      />
      <path
        d="M115.287 19.1163C114.424 19.1163 113.535 18.9304 112.645 18.5586C111.755 18.1868 111.012 17.6424 110.414 16.9386L112.1 15.5045C112.525 15.8763 112.95 16.1817 113.375 16.4075C113.813 16.6332 114.358 16.766 115.048 16.8058C115.752 16.8457 116.35 16.766 116.828 16.5535C117.306 16.3411 117.558 16.0357 117.584 15.6107C117.598 15.3186 117.518 15.0929 117.345 14.9335C117.173 14.7742 116.907 14.6281 116.535 14.5219C116.164 14.4157 115.593 14.2962 114.809 14.1634L114.265 14.0572C113.123 13.8713 112.246 13.5127 111.622 12.9949C110.998 12.477 110.693 11.7334 110.693 10.7906C110.693 10.0072 110.905 9.34329 111.317 8.77231C111.742 8.21461 112.286 7.7897 112.99 7.51085C113.681 7.232 114.451 7.08594 115.314 7.08594C116.19 7.08594 117.053 7.24528 117.863 7.56396C118.687 7.88265 119.364 8.40051 119.882 9.10427L118.209 10.5118C117.903 10.1267 117.505 9.83459 117 9.63541C116.496 9.43624 115.951 9.34329 115.354 9.34329C114.969 9.34329 114.597 9.38312 114.252 9.47607C113.906 9.56902 113.614 9.70181 113.388 9.90098C113.163 10.1002 113.043 10.3392 113.043 10.6446C113.043 10.9102 113.123 11.1093 113.269 11.2554C113.415 11.4015 113.694 11.5342 114.079 11.6405C114.464 11.7467 115.128 11.8928 116.044 12.0654H116.084C117.226 12.2778 118.169 12.6762 118.899 13.2339C119.629 13.7916 120.001 14.5617 120.001 15.5045C120.001 16.2348 119.775 16.8855 119.324 17.4299C118.872 17.9743 118.288 18.3992 117.558 18.6914C116.841 18.9702 116.084 19.1163 115.287 19.1163Z"
        fill="currentColor"
      />
      <path
        d="M14.7392 9.80759C14.5931 9.92709 14.3806 9.83414 14.3806 9.63497V8.58596V2.23883C14.3806 2.05293 14.1549 1.9467 14.0221 2.06621L5.17862 9.56857C5.03256 9.68808 4.8201 9.59513 4.8201 9.39595V4.27044C4.8201 4.12438 4.70059 4.00487 4.55453 4.00487H0.26557C0.119507 4.00487 0 4.12438 0 4.27044V20.3242C0 20.5101 0.225735 20.6163 0.35852 20.4968L9.18873 12.9944C9.33479 12.8749 9.54725 12.9679 9.54725 13.1671V20.5765C9.54725 20.7624 9.77299 20.8686 9.90577 20.7491L18.736 13.2467C18.882 13.1272 19.0945 13.2202 19.0945 13.4193V18.5449C19.0945 18.6909 19.214 18.8104 19.3601 18.8104H23.649C23.7951 18.8104 23.9146 18.6909 23.9146 18.5449V2.47784C23.9146 2.29194 23.6889 2.18572 23.5561 2.30522L14.7392 9.80759Z"
        fill="currentColor"
      />
    </svg>
  );
}
