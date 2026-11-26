"use client";

import { GitHubLogoIcon } from "@radix-ui/react-icons";
import { BookOpen, MessageSquare } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import {
  type LandingDocsLang,
  type LandingLocale,
  useOptionalLandingLocale,
} from "@/core/i18n/landing";
import { cn } from "@/lib/utils";

export type FooterProps = {
  className?: string;
  locale?: LandingLocale;
};

type FooterLink = {
  label: string;
  href: string;
  external?: boolean;
};

type FooterColumn = {
  heading: string;
  links: FooterLink[];
};

function getFooterCopy(locale: LandingLocale, docsLang: LandingDocsLang) {
  const isZh = locale === "zh-CN";

  const columns: FooterColumn[] = [
    {
      heading: isZh ? "产品" : "Product",
      links: [
        { label: isZh ? "架构总览" : "Architecture", href: "/#architecture" },
        { label: isZh ? "精选案例" : "Case Studies", href: "/#case-studies" },
        { label: isZh ? "技能系统" : "Skills", href: "/#skills" },
        { label: isZh ? "隔离沙箱" : "Sandbox", href: "/#sandbox" },
        { label: isZh ? "最新特性" : "What's New", href: "/#whats-new" },
      ],
    },
    {
      heading: isZh ? "生态集成" : "Integrations",
      links: [
        {
          label: isZh ? "模型与服务商" : "Models & Providers",
          href: `/${docsLang}/docs/reference/model-providers`,
        },
        {
          label: isZh ? "MCP 工具" : "MCP Tools",
          href: `/${docsLang}/docs/harness/mcp`,
        },
        {
          label: isZh ? "技能生态" : "Skills Ecosystem",
          href: `/${docsLang}/docs/harness/skills`,
        },
        {
          label: isZh ? "扩展与插件" : "Extensions",
          href: `/${docsLang}/docs/harness/extensions`,
        },
        {
          label: isZh ? "IM 渠道" : "IM Channels",
          href: `/${docsLang}/docs/application/configuration`,
        },
      ],
    },
    {
      heading: isZh ? "开发者" : "Developers",
      links: [
        {
          label: isZh ? "快速开始" : "Quick Start",
          href: `/${docsLang}/docs/application/quick-start`,
        },
        {
          label: isZh ? "完整文档" : "Documentation",
          href: `/${docsLang}/docs`,
        },
        {
          label: isZh ? "Harness 指南" : "Harness Guide",
          href: `/${docsLang}/docs/harness/quick-start`,
        },
        {
          label: isZh ? "部署指南" : "Deployment",
          href: `/${docsLang}/docs/application/deployment-guide`,
        },
        { label: isZh ? "技术博客" : "Blog", href: "/blog/posts" },
      ],
    },
    {
      heading: isZh ? "开源社区" : "Community",
      links: [
        {
          label: "GitHub",
          href: "https://github.com/bytedance/deer-flow",
          external: true,
        },
        {
          label: isZh ? "社区讨论" : "Discussions",
          href: "https://github.com/bytedance/deer-flow/discussions",
          external: true,
        },
        {
          label: isZh ? "问题反馈" : "Issues",
          href: "https://github.com/bytedance/deer-flow/issues",
          external: true,
        },
        {
          label: isZh ? "参与贡献" : "Contributing",
          href: "https://github.com/bytedance/deer-flow/blob/main/CONTRIBUTING.md",
          external: true,
        },
        {
          label: isZh ? "进入工作区" : "Open Workspace",
          href: "/workspace/chats/new",
        },
      ],
    },
  ];

  return {
    tagline: isZh
      ? "开源超级智能体 Harness，集成沙箱、记忆、技能与 MCP 工具。"
      : "Open-source super agent harness with sandboxes, memory, skills, and MCP tools.",
    quote: '"Originated from Open Source, give back to Open Source."',
    license: isZh ? "基于 MIT 许可证开源" : "Licensed under MIT License",
    githubAriaLabel: isZh ? "DeerFlow GitHub 仓库" : "DeerFlow on GitHub",
    discussionsAriaLabel: isZh ? "GitHub 讨论区" : "GitHub Discussions",
    docsAriaLabel: isZh ? "DeerFlow 文档" : "DeerFlow Documentation",
    columns,
  };
}

export function Footer({ className, locale }: FooterProps) {
  const { locale: activeLocale, docsLang } = useOptionalLandingLocale(locale);
  const year = useMemo(() => new Date().getFullYear(), []);
  const copy = getFooterCopy(activeLocale, docsLang);

  return (
    <footer
      className={cn(
        "border-t border-[var(--df-border)] bg-[var(--df-bg-soft)] pt-16 pb-8 text-[var(--df-ink)]",
        className,
      )}
    >
      <div className="mx-auto max-w-[1280px] px-4 sm:px-8 lg:px-12">
        <div className="grid grid-cols-2 gap-10 md:grid-cols-5">
          <div className="col-span-2 flex flex-col gap-4 md:col-span-1">
            <Link
              href="/"
              className="focus-visible:ring-ring/50 w-fit rounded-sm font-serif text-xl font-semibold tracking-tight text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none"
            >
              DeerFlow
            </Link>
            <p className="max-w-xs text-sm leading-6 text-[var(--df-muted-fg)]">
              {copy.tagline}
            </p>
            <div className="flex items-center gap-2">
              <a
                href="https://github.com/bytedance/deer-flow"
                target="_blank"
                rel="noopener noreferrer"
                aria-label={copy.githubAriaLabel}
                className="focus-visible:ring-ring/50 inline-flex h-9 w-9 items-center justify-center rounded-md border border-[var(--df-border)] bg-[var(--df-panel)] text-[var(--df-muted-fg)] transition-colors duration-150 hover:border-[var(--df-border-strong)] hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none"
              >
                <GitHubLogoIcon className="size-4" aria-hidden="true" />
              </a>
              <a
                href="https://github.com/bytedance/deer-flow/discussions"
                target="_blank"
                rel="noopener noreferrer"
                aria-label={copy.discussionsAriaLabel}
                className="focus-visible:ring-ring/50 inline-flex h-9 w-9 items-center justify-center rounded-md border border-[var(--df-border)] bg-[var(--df-panel)] text-[var(--df-muted-fg)] transition-colors duration-150 hover:border-[var(--df-border-strong)] hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none"
              >
                <MessageSquare className="size-4" aria-hidden="true" />
              </a>
              <Link
                href={`/${docsLang}/docs`}
                aria-label={copy.docsAriaLabel}
                className="focus-visible:ring-ring/50 inline-flex h-9 w-9 items-center justify-center rounded-md border border-[var(--df-border)] bg-[var(--df-panel)] text-[var(--df-muted-fg)] transition-colors duration-150 hover:border-[var(--df-border-strong)] hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none"
              >
                <BookOpen className="size-4" aria-hidden="true" />
              </Link>
            </div>
          </div>

          {copy.columns.map((column) => (
            <div key={column.heading} className="flex flex-col gap-3">
              <h3 className="font-mono text-xs font-semibold tracking-[0.16em] text-[var(--df-ink)] uppercase">
                {column.heading}
              </h3>
              <ul className="flex flex-col gap-2.5">
                {column.links.map((link) => (
                  <li key={link.href}>
                    {link.external ? (
                      <a
                        href={link.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="focus-visible:ring-ring/50 rounded-sm text-sm text-[var(--df-muted-fg)] transition-colors duration-150 hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none"
                      >
                        {link.label}
                      </a>
                    ) : (
                      <Link
                        href={link.href}
                        className="focus-visible:ring-ring/50 rounded-sm text-sm text-[var(--df-muted-fg)] transition-colors duration-150 hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none"
                      >
                        {link.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-14 flex flex-col items-center justify-between gap-2 border-t border-[var(--df-border)] pt-8 text-center text-xs text-[var(--df-muted-fg)] sm:flex-row sm:text-left">
          <p className="font-serif text-sm text-[var(--df-text-soft)]">
            {copy.quote}
          </p>
          <p>
            {copy.license} &middot; &copy; {year} DeerFlow
          </p>
        </div>
      </div>
    </footer>
  );
}
