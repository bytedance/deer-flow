"use client";

import { ArrowUpRight, Terminal as TerminalIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import {
  DEFAULT_LOCALE,
  getLangByLocale,
  type Locale,
} from "@/core/i18n/locale";
import { cn } from "@/lib/utils";

import { Section } from "../section";

type TerminalLine = {
  kind: "command" | "output" | "success" | "info";
  text: string;
};

type TerminalScene = {
  id: string;
  tabLabel: string;
  cwd: string;
  lines: TerminalLine[];
};

const TERMINAL_SCENES: TerminalScene[] = [
  {
    id: "game",
    tabLabel: "build-and-test",
    cwd: "/mnt/user-data/workspace",
    lines: [
      { kind: "command", text: "cat requirements.txt" },
      { kind: "output", text: "pygame==2.5.0" },
      { kind: "command", text: "pip install -r requirements.txt" },
      { kind: "success", text: "✔ Installed pygame==2.5.0" },
      { kind: "command", text: "write game.py --lines 156" },
      {
        kind: "info",
        text: "✔ Written 156 lines to /mnt/user-data/workspace/game.py",
      },
      { kind: "command", text: "python game.py --test" },
      { kind: "success", text: "✔ All sprites loaded" },
      { kind: "success", text: "✔ Physics engine OK" },
      { kind: "success", text: "✔ 60 FPS stable" },
    ],
  },
  {
    id: "data",
    tabLabel: "data-pipeline",
    cwd: "/mnt/user-data/workspace",
    lines: [
      {
        kind: "command",
        text: "curl -sO https://datasets.local/sales-2024.csv",
      },
      { kind: "output", text: "Downloaded 12.4 MB (148,290 rows)" },
      {
        kind: "command",
        text: "python analyze.py sales-2024.csv --out /mnt/user-data/outputs/report.html",
      },
      {
        kind: "info",
        text: "Running pandas + matplotlib in isolated container…",
      },
      { kind: "success", text: "✔ Generated 4 interactive charts" },
      { kind: "success", text: "✔ Saved /mnt/user-data/outputs/report.html" },
    ],
  },
];

type SandboxCopy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  runtimeLabel: string;
  runtimeTitle: string;
  runtimePrefix: string;
  runtimeLinkText: string;
  runtimeSuffix: string;
  mountsHeading: string;
  mounts: { path: string; note: string }[];
  tags: string[];
  docsLink: string;
};

const SANDBOX_COPY: Record<Locale, SandboxCopy> = {
  "en-US": {
    eyebrow: "Isolated Execution",
    title: "Agent Runtime Environment",
    subtitle:
      'We give DeerFlow a "computer" that executes commands, manages files, and runs long tasks — all inside a thread-isolated sandbox.',
    runtimeLabel: "Open-Source Sandbox",
    runtimeTitle: "AIO Sandbox",
    runtimePrefix: "We recommend using ",
    runtimeLinkText: "All-in-One Sandbox",
    runtimeSuffix:
      " combining Browser, Shell, File, MCP, and VSCode Server in a single Docker container — or run locally and on Kubernetes.",
    mountsHeading: "Thread-isolated mounts",
    mounts: [
      { path: "/mnt/user-data/workspace", note: "Working directory & scripts" },
      { path: "/mnt/user-data/uploads", note: "User attachments (read-only)" },
      { path: "/mnt/user-data/outputs", note: "Delivered files & artifacts" },
    ],
    tags: ["Isolated", "Safe", "Persistent", "Mountable FS", "Long-running"],
    docsLink: "Read Sandbox Docs",
  },
  "zh-CN": {
    eyebrow: "隔离执行环境",
    title: "智能体运行时沙箱",
    subtitle:
      "为 DeerFlow 配备一台真正的「电脑」：在会话隔离的沙箱中执行命令、管理文件并运行长耗时任务。",
    runtimeLabel: "开源沙箱",
    runtimeTitle: "AIO Sandbox",
    runtimePrefix: "推荐使用 ",
    runtimeLinkText: "All-in-One Sandbox",
    runtimeSuffix:
      "，在单个 Docker 容器中集成浏览器、Shell、文件系统、MCP 与 VSCode Server；同时也支持本地与 Kubernetes 部署。",
    mountsHeading: "会话隔离挂载目录",
    mounts: [
      { path: "/mnt/user-data/workspace", note: "工作目录与代码脚本" },
      { path: "/mnt/user-data/uploads", note: "用户上传文件" },
      { path: "/mnt/user-data/outputs", note: "最终交付物与报告" },
    ],
    tags: ["会话隔离", "安全可控", "持久化", "可挂载文件系统", "长任务支持"],
    docsLink: "查看沙箱文档",
  },
};

export function SandboxSection({
  className,
  locale = DEFAULT_LOCALE,
}: {
  className?: string;
  locale?: Locale;
}) {
  const copy = SANDBOX_COPY[locale] ?? SANDBOX_COPY["en-US"];
  const lang = getLangByLocale(locale);
  const [activeSceneId, setActiveSceneId] = useState(TERMINAL_SCENES[0]!.id);
  const activeScene =
    TERMINAL_SCENES.find((scene) => scene.id === activeSceneId) ??
    TERMINAL_SCENES[0]!;

  return (
    <Section
      id="sandbox"
      variant="soft"
      className={className}
      eyebrow={copy.eyebrow}
      title={copy.title}
      subtitle={copy.subtitle}
    >
      <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)] lg:gap-12">
        {/* Left: Editorial Terminal Panel */}
        <div className="min-w-0 overflow-hidden rounded-md border border-[var(--df-border,#d8d0c2)] bg-[var(--df-panel,#fffaf1)]">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--df-border,#d8d0c2)] bg-[var(--df-muted,#f4edde)]/60 px-4 py-2.5">
            <div className="flex min-w-0 items-center gap-2 font-mono text-xs text-[var(--df-muted-fg,#625b50)]">
              <TerminalIcon
                className="size-3.5 shrink-0 text-[var(--df-accent,#0a7c93)]"
                aria-hidden="true"
              />
              <span className="truncate">{activeScene.cwd}</span>
            </div>

            <div
              className="flex items-center gap-1"
              role="tablist"
              aria-label="Sandbox terminal examples"
            >
              {TERMINAL_SCENES.map((scene) => {
                const isSelected = scene.id === activeScene.id;
                return (
                  <button
                    key={scene.id}
                    type="button"
                    role="tab"
                    aria-selected={isSelected}
                    onClick={() => setActiveSceneId(scene.id)}
                    className={cn(
                      "focus-visible:ring-ring/50 min-h-[30px] rounded border px-2.5 py-0.5 font-mono text-[11px] font-medium transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none",
                      isSelected
                        ? "border-[var(--df-accent,#0a7c93)] bg-[var(--df-panel,#fffaf1)] text-[var(--df-ink,#171511)]"
                        : "border-transparent text-[var(--df-muted-fg,#625b50)] hover:text-[var(--df-ink,#171511)]",
                    )}
                  >
                    {scene.tabLabel}
                  </button>
                );
              })}
            </div>
          </div>

          <pre className="overflow-x-auto p-5 font-mono text-xs leading-6 sm:p-6 sm:text-[13px]">
            <code className="block space-y-1.5">
              {activeScene.lines.map((line, index) => (
                <div key={`${activeScene.id}-${index}`} className="flex gap-2">
                  {line.kind === "command" && (
                    <>
                      <span
                        className="shrink-0 font-semibold text-[var(--df-accent,#0a7c93)] select-none"
                        aria-hidden="true"
                      >
                        $
                      </span>
                      <span className="font-medium text-[var(--df-ink,#171511)]">
                        {line.text}
                      </span>
                    </>
                  )}
                  {line.kind === "output" && (
                    <span className="pl-4 text-[var(--df-muted-fg,#625b50)]">
                      {line.text}
                    </span>
                  )}
                  {line.kind === "info" && (
                    <span className="pl-4 text-[var(--df-accent,#0a7c93)]">
                      {line.text}
                    </span>
                  )}
                  {line.kind === "success" && (
                    <span className="pl-4 text-emerald-700 dark:text-emerald-400">
                      {line.text}
                    </span>
                  )}
                </div>
              ))}
            </code>
          </pre>
        </div>

        {/* Right: Runtime Details & Capability Chips */}
        <div className="min-w-0 space-y-6">
          <div className="space-y-3">
            <p className="font-mono text-xs font-medium tracking-[0.2em] text-[var(--df-accent,#0a7c93)] uppercase">
              {copy.runtimeLabel}
            </p>
            <h3 className="text-xl font-semibold tracking-tight text-[var(--df-ink,#171511)] sm:text-2xl">
              <a
                href="https://github.com/agent-infra/sandbox"
                target="_blank"
                rel="noopener noreferrer"
                className="focus-visible:ring-ring/50 inline-flex items-center gap-1.5 rounded transition-colors duration-150 hover:text-[var(--df-accent,#0a7c93)] focus-visible:ring-2 focus-visible:outline-none"
              >
                <span>{copy.runtimeTitle}</span>
                <ArrowUpRight className="size-4" aria-hidden="true" />
              </a>
            </h3>
            <p className="text-sm leading-7 text-[var(--df-muted-fg,#625b50)] sm:text-base">
              {copy.runtimePrefix}
              <a
                href="https://github.com/agent-infra/sandbox"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-[var(--df-ink,#171511)] underline decoration-[var(--df-border-strong,#bdb3a2)] underline-offset-4 transition-colors duration-150 hover:text-[var(--df-accent,#0a7c93)] hover:decoration-[var(--df-accent,#0a7c93)]"
              >
                {copy.runtimeLinkText}
              </a>
              {copy.runtimeSuffix}
            </p>
          </div>

          <div className="rounded-md border border-[var(--df-border,#d8d0c2)] bg-[var(--df-panel,#fffaf1)] p-4">
            <p className="font-mono text-[11px] font-medium tracking-[0.16em] text-[var(--df-muted-fg,#625b50)] uppercase">
              {copy.mountsHeading}
            </p>
            <dl className="mt-3 space-y-2 border-l border-[var(--df-border-soft,#ded6c7)] pl-3.5">
              {copy.mounts.map((mount) => (
                <div
                  key={mount.path}
                  className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4"
                >
                  <dt className="font-mono text-xs font-medium break-all text-[var(--df-ink,#171511)]">
                    {mount.path}
                  </dt>
                  <dd className="text-xs text-[var(--df-muted-fg,#625b50)]">
                    {mount.note}
                  </dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="flex flex-wrap gap-2">
            {copy.tags.map((tag) => (
              <span
                key={tag}
                className="rounded border border-[var(--df-border,#d8d0c2)] bg-[var(--df-surface,#fbf6ec)] px-2.5 py-1 font-mono text-xs text-[var(--df-text-soft,#3a352d)]"
              >
                {tag}
              </span>
            ))}
          </div>

          <div>
            <Link
              href={`/${lang}/docs/harness/sandbox`}
              className="focus-visible:ring-ring/50 inline-flex items-center gap-1.5 rounded font-mono text-xs font-medium text-[var(--df-accent,#0a7c93)] transition-colors duration-150 hover:text-[var(--df-accent-strong,#086a7e)] focus-visible:ring-2 focus-visible:outline-none"
            >
              <span>{copy.docsLink}</span>
              <ArrowUpRight className="size-3.5" aria-hidden="true" />
            </Link>
          </div>
        </div>
      </div>
    </Section>
  );
}
