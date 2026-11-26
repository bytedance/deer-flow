"use client";

import {
  ArrowUpRight,
  Box,
  FolderGit2,
  HardDrive,
  Laptop,
  Server,
  Terminal as TerminalIcon,
} from "lucide-react";
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
  artifact: string;
  lines: TerminalLine[];
};

const TERMINAL_SCENES: TerminalScene[] = [
  {
    id: "game",
    tabLabel: "build-and-test",
    cwd: "/mnt/user-data/workspace",
    artifact: "/mnt/user-data/workspace/game.py",
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
    artifact: "/mnt/user-data/outputs/report.html",
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

type RuntimeBackend = {
  id: "local" | "docker" | "k8s";
  label: string;
};

type MountItem = {
  path: string;
  mode: "rw" | "ro";
  note: string;
};

type SandboxCopy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  topologyTitle: string;
  containerBadge: string;
  mounts: MountItem[];
  backendsHeading: string;
  backends: RuntimeBackend[];
  runtimePrefix: string;
  runtimeLinkText: string;
  runtimeSuffix: string;
  docsLink: string;
  terminalAriaLabel: string;
  statusIsolated: string;
};

const SANDBOX_COPY: Record<Locale, SandboxCopy> = {
  "en-US": {
    eyebrow: "Isolated Runtime",
    title: "Agent Runtime Environment",
    subtitle:
      'Give every thread its own "computer" — scoped mounts, shell execution, browser automation, and long-running builds safely isolated per session.',
    topologyTitle: "Thread Mount Topology",
    containerBadge: "thread-isolated",
    mounts: [
      {
        path: "/mnt/user-data/workspace",
        mode: "rw",
        note: "Working directory, code & intermediate scripts",
      },
      {
        path: "/mnt/user-data/uploads",
        mode: "ro",
        note: "User-attached datasets, documents & assets",
      },
      {
        path: "/mnt/user-data/outputs",
        mode: "rw",
        note: "Delivered reports, charts & downloadable artifacts",
      },
    ],
    backendsHeading: "Runtime Backends",
    backends: [
      { id: "local", label: "Local" },
      { id: "docker", label: "Docker" },
      { id: "k8s", label: "Kubernetes" },
    ],
    runtimePrefix: "Recommended container: ",
    runtimeLinkText: "All-in-One Sandbox",
    runtimeSuffix:
      " — Browser, Shell, File, MCP, and VSCode Server in one image.",
    docsLink: "Read Sandbox Docs",
    terminalAriaLabel: "Sandbox terminal examples",
    statusIsolated: "exit 0 · isolated fs",
  },
  "zh-CN": {
    eyebrow: "隔离运行时",
    title: "智能体运行时沙箱",
    subtitle:
      "为每个会话配备独立「电脑」：隔离挂载目录、完整 Shell、浏览器与长耗时构建均在安全边界内运行。",
    topologyTitle: "会话挂载拓扑",
    containerBadge: "会话级隔离",
    mounts: [
      {
        path: "/mnt/user-data/workspace",
        mode: "rw",
        note: "工作目录、代码脚本与临时构建产物",
      },
      {
        path: "/mnt/user-data/uploads",
        mode: "ro",
        note: "用户上传的数据集、文档与附件资源",
      },
      {
        path: "/mnt/user-data/outputs",
        mode: "rw",
        note: "最终交付报告、可视化图表与可下载文件",
      },
    ],
    backendsHeading: "支持运行后端",
    backends: [
      { id: "local", label: "Local" },
      { id: "docker", label: "Docker" },
      { id: "k8s", label: "Kubernetes" },
    ],
    runtimePrefix: "推荐使用 ",
    runtimeLinkText: "All-in-One Sandbox",
    runtimeSuffix: " — 单镜像集成浏览器、Shell、文件系统、MCP 与 VSCode。",
    docsLink: "查看沙箱文档",
    terminalAriaLabel: "沙箱终端示例",
    statusIsolated: "exit 0 · 隔离文件系统",
  },
};

function BackendIcon({ id }: { id: RuntimeBackend["id"] }) {
  if (id === "local") {
    return <Laptop className="size-3.5 shrink-0" aria-hidden="true" />;
  }
  if (id === "docker") {
    return <Box className="size-3.5 shrink-0" aria-hidden="true" />;
  }
  return <Server className="size-3.5 shrink-0" aria-hidden="true" />;
}

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
      index="03"
      variant="soft"
      className={className}
      eyebrow={copy.eyebrow}
      title={copy.title}
      subtitle={copy.subtitle}
    >
      <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-12 lg:gap-10">
        {/* Left: Visual Mount-Path Topology & Runtime Backends */}
        <div className="min-w-0 space-y-5 lg:col-span-5">
          <div className="rounded-xl border border-[var(--df-border)] bg-[var(--df-panel)] p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--df-border-soft)] pb-3.5">
              <div className="flex items-center gap-2">
                <HardDrive
                  className="size-4 shrink-0 text-[var(--df-accent)]"
                  aria-hidden="true"
                />
                <h3 className="font-mono text-xs font-semibold tracking-[0.12em] text-[var(--df-ink)] uppercase">
                  {copy.topologyTitle}
                </h3>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--df-accent-soft,rgba(28,93,74,0.09))] px-2.5 py-0.5 font-mono text-[10px] font-medium text-[var(--df-accent)]">
                <span
                  className="size-1.5 rounded-full bg-[var(--df-accent)]"
                  aria-hidden="true"
                />
                {copy.containerBadge}
              </span>
            </div>

            <div className="mt-4 space-y-2.5 border-l-2 border-[var(--df-border)] pl-3.5">
              {copy.mounts.map((mount) => (
                <div
                  key={mount.path}
                  className="rounded-lg border border-[var(--df-border-soft)] bg-[var(--df-surface)] px-3.5 py-2.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-1.5 font-mono text-xs font-semibold break-all text-[var(--df-ink)]">
                      <FolderGit2
                        className="size-3.5 shrink-0 text-[var(--df-accent)]"
                        aria-hidden="true"
                      />
                      <span>{mount.path}</span>
                    </span>
                    <span className="shrink-0 rounded border border-[var(--df-border)] bg-[var(--df-panel)] px-1.5 py-0.5 font-mono text-[10px] font-medium text-[var(--df-accent)] uppercase">
                      {mount.mode}
                    </span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-[var(--df-muted-fg)]">
                    {mount.note}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-[var(--df-border)] bg-[var(--df-panel)] p-5">
            <p className="font-mono text-[11px] font-semibold tracking-[0.14em] text-[var(--df-muted-fg)] uppercase">
              {copy.backendsHeading}
            </p>

            <div className="mt-3 flex flex-wrap gap-2">
              {copy.backends.map((backend) => (
                <span
                  key={backend.id}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[var(--df-border)] bg-[var(--df-surface)] px-3 py-1 font-mono text-xs font-medium text-[var(--df-ink)]"
                >
                  <span className="text-[var(--df-accent)]">
                    <BackendIcon id={backend.id} />
                  </span>
                  <span>{backend.label}</span>
                </span>
              ))}
            </div>

            <p className="mt-3.5 text-xs leading-6 text-[var(--df-muted-fg)] sm:text-sm">
              {copy.runtimePrefix}
              <a
                href="https://github.com/agent-infra/sandbox"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-[var(--df-ink)] underline decoration-[var(--df-border-strong)] underline-offset-4 transition-colors duration-150 hover:text-[var(--df-accent)] hover:decoration-[var(--df-accent)]"
              >
                {copy.runtimeLinkText}
              </a>
              {copy.runtimeSuffix}
            </p>

            <div className="mt-4 border-t border-[var(--df-border-soft)] pt-3.5">
              <Link
                href={`/${lang}/docs/harness/sandbox`}
                className="focus-visible:ring-ring/50 inline-flex items-center gap-1.5 rounded font-mono text-xs font-medium text-[var(--df-accent)] transition-colors duration-150 hover:text-[var(--df-accent-strong)] focus-visible:ring-2 focus-visible:outline-none"
              >
                <span>{copy.docsLink}</span>
                <ArrowUpRight className="size-3.5" aria-hidden="true" />
              </Link>
            </div>
          </div>
        </div>

        {/* Right: Editorial Interactive Console */}
        <div className="min-w-0 overflow-hidden rounded-2xl border border-[var(--df-border)] bg-[var(--df-panel)] shadow-[0_10px_28px_var(--df-shadow)] lg:col-span-7">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--df-border)] bg-[var(--df-bg-soft)] px-4 py-3 sm:px-5">
            <div className="flex min-w-0 items-center gap-2 font-mono text-xs text-[var(--df-text-soft)]">
              <TerminalIcon
                className="size-3.5 shrink-0 text-[var(--df-accent)]"
                aria-hidden="true"
              />
              <span className="truncate">{activeScene.cwd}</span>
            </div>

            <div
              className="flex flex-wrap items-center gap-1.5"
              role="tablist"
              aria-label={copy.terminalAriaLabel}
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
                      "focus-visible:ring-ring/50 min-h-[32px] rounded-full px-3 py-1 font-mono text-[11px] font-medium transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none",
                      isSelected
                        ? "bg-[var(--df-cta)] text-[var(--df-cta-fg)]"
                        : "border border-[var(--df-border)] bg-[var(--df-panel)] text-[var(--df-muted-fg)] hover:border-[var(--df-accent)]/50 hover:text-[var(--df-ink)]",
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
                        className="shrink-0 font-semibold text-[var(--df-accent)] select-none"
                        aria-hidden="true"
                      >
                        $
                      </span>
                      <span className="font-medium text-[var(--df-ink)]">
                        {line.text}
                      </span>
                    </>
                  )}
                  {line.kind === "output" && (
                    <span className="pl-4 text-[var(--df-muted-fg)]">
                      {line.text}
                    </span>
                  )}
                  {line.kind === "info" && (
                    <span className="pl-4 text-[var(--df-accent)]">
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

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--df-border-soft)] bg-[var(--df-surface)] px-5 py-2.5 font-mono text-[11px] text-[var(--df-muted-fg)]">
            <span className="inline-flex items-center gap-1.5 text-[var(--df-accent)]">
              <span
                className="size-1.5 rounded-full bg-[var(--df-accent)]"
                aria-hidden="true"
              />
              {copy.statusIsolated}
            </span>
            <span className="truncate">{activeScene.artifact}</span>
          </div>
        </div>
      </div>
    </Section>
  );
}
