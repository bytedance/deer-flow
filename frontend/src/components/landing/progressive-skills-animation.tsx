"use client";

import {
  Check,
  FileText,
  Folder,
  Globe,
  Pause,
  Play,
  RotateCcw,
  Search,
  Terminal,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { usePrefersReducedMotion } from "@/core/dom/render-activity";
import { DEFAULT_LOCALE, type Locale } from "@/core/i18n/locale";
import { cn } from "@/lib/utils";

type AnimationPhase =
  | "scanning"
  | "load-skill"
  | "load-template"
  | "researching"
  | "load-frontend"
  | "building"
  | "load-deploy"
  | "deploying"
  | "done";

const PHASE_ORDER: readonly AnimationPhase[] = [
  "scanning",
  "load-skill",
  "load-template",
  "researching",
  "load-frontend",
  "building",
  "load-deploy",
  "deploying",
  "done",
];

const PHASE_DURATION_MS: Record<AnimationPhase, number> = {
  scanning: 1600,
  "load-skill": 1300,
  "load-template": 1300,
  researching: 2200,
  "load-frontend": 1200,
  building: 2000,
  "load-deploy": 1300,
  deploying: 1400,
  done: 3500,
};

interface FileItem {
  name: string;
  type: "folder" | "file";
  indent: number;
  highlight?: boolean;
  active?: boolean;
  done?: boolean;
  skipped?: boolean;
}

const SEARCH_STEPS = [
  { type: "search" as const, text: "mRNA lipid nanoparticle delivery 2024" },
  { type: "fetch" as const, text: "nature.com/articles/s41587-024..." },
  { type: "search" as const, text: "LNP ionizable lipids efficiency" },
  { type: "fetch" as const, text: "pubs.acs.org/doi/10.1021/..." },
  { type: "search" as const, text: "targeted mRNA tissue-specific" },
];

const WORKSPACE_FILES = ["index.html", "index.css", "index.js"];

type StageTab = {
  id: string;
  phase: AnimationPhase;
  label: string;
};

type AnimationCopy = {
  treeHeader: string;
  agentLabel: string;
  promptBadge: string;
  promptText: string;
  play: string;
  pause: string;
  replay: string;
  loadedTag: string;
  loadingTag: string;
  skippedTag: string;
  foundSkills: string;
  researchingHeading: string;
  loadingDeepSearch: string;
  loadingBiotech: string;
  buildingHeading: string;
  loadingFrontend: string;
  generatingPrefix: string;
  deployingHeading: string;
  loadingDeploy: string;
  executingDeploy: string;
  liveBanner: string;
  stages: StageTab[];
  phaseStatus: Record<AnimationPhase, string>;
};

const ANIMATION_COPY: Record<Locale, AnimationCopy> = {
  "en-US": {
    treeHeader: "/mnt/skills/",
    agentLabel: "deerflow-agent",
    promptBadge: "PROMPT",
    promptText:
      "Research mRNA delivery, build a landing page, deploy to Vercel",
    play: "Play",
    pause: "Pause",
    replay: "Reset",
    loadedTag: "loaded",
    loadingTag: "loading",
    skippedTag: "skipped",
    foundSkills: "Matched 3 relevant skills from /mnt/skills/",
    researchingHeading: "1 · Deep Research",
    loadingDeepSearch: "Loaded deep-search/SKILL.md",
    loadingBiotech: "Biotech domain detected — loaded deep-search/biotech.md",
    buildingHeading: "2 · Frontend Build",
    loadingFrontend: "Loaded frontend-design/SKILL.md",
    generatingPrefix: "Generated",
    deployingHeading: "3 · Deploy",
    loadingDeploy: "Loaded deploy/SKILL.md",
    executingDeploy: "Executed scripts/deploy.sh",
    liveBanner: "Live at biotech-startup.vercel.app",
    stages: [
      { id: "scan", phase: "scanning", label: "01 Scan" },
      { id: "research", phase: "researching", label: "02 Research" },
      { id: "build", phase: "building", label: "03 Build" },
      { id: "deploy", phase: "done", label: "04 Deploy" },
    ],
    phaseStatus: {
      scanning: "Scanning manifest",
      "load-skill": "Loading deep-search",
      "load-template": "Loading biotech.md",
      researching: "Researching sources",
      "load-frontend": "Loading frontend-design",
      building: "Building artifacts",
      "load-deploy": "Loading deploy",
      deploying: "Running deploy.sh",
      done: "Complete",
    },
  },
  "zh-CN": {
    treeHeader: "/mnt/skills/",
    agentLabel: "deerflow-agent",
    promptBadge: "任务指令",
    promptText: "调研 mRNA 递送技术，构建一个展示网页并部署到 Vercel",
    play: "播放",
    pause: "暂停",
    replay: "重置",
    loadedTag: "已加载",
    loadingTag: "加载中",
    skippedTag: "按需跳过",
    foundSkills: "从 /mnt/skills/ 匹配到 3 个相关技能",
    researchingHeading: "1 · 深度研究",
    loadingDeepSearch: "已加载 deep-search/SKILL.md",
    loadingBiotech: "识别生物医药主题 — 按需加载 deep-search/biotech.md",
    buildingHeading: "2 · 前端构建",
    loadingFrontend: "已加载 frontend-design/SKILL.md",
    generatingPrefix: "已生成",
    deployingHeading: "3 · 自动部署",
    loadingDeploy: "已加载 deploy/SKILL.md",
    executingDeploy: "执行 scripts/deploy.sh",
    liveBanner: "已上线至 biotech-startup.vercel.app",
    stages: [
      { id: "scan", phase: "scanning", label: "01 扫描" },
      { id: "research", phase: "researching", label: "02 调研" },
      { id: "build", phase: "building", label: "03 构建" },
      { id: "deploy", phase: "done", label: "04 部署" },
    ],
    phaseStatus: {
      scanning: "扫描技能清单",
      "load-skill": "加载 deep-search",
      "load-template": "加载 biotech.md",
      researching: "检索权威资料",
      "load-frontend": "加载 frontend-design",
      building: "生成页面文件",
      "load-deploy": "加载 deploy",
      deploying: "运行 deploy.sh",
      done: "已完成",
    },
  },
};

function phaseIndex(phase: AnimationPhase): number {
  return PHASE_ORDER.indexOf(phase);
}

export default function ProgressiveSkillsAnimation({
  locale = DEFAULT_LOCALE,
  className,
}: {
  locale?: Locale;
  className?: string;
}) {
  const copy = ANIMATION_COPY[locale] ?? ANIMATION_COPY["en-US"];
  const reducedMotion = usePrefersReducedMotion();
  const [phase, setPhase] = useState<AnimationPhase>("load-template");
  const [isPlaying, setIsPlaying] = useState(false);
  const [hasAutoPlayed, setHasAutoPlayed] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const currentIdx = phaseIndex(phase);

  // Start playing automatically once visible unless reduced motion is preferred.
  useEffect(() => {
    if (reducedMotion) {
      setIsPlaying(false);
      setPhase("done");
      return;
    }
    if (hasAutoPlayed || !containerRef.current) return;
    if (typeof IntersectionObserver === "undefined") return;

    const element = containerRef.current;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setHasAutoPlayed(true);
          setPhase("scanning");
          setIsPlaying(true);
        }
      },
      { threshold: 0.25 },
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, [hasAutoPlayed, reducedMotion]);

  // Step through phases calmly when playing.
  useEffect(() => {
    if (!isPlaying || reducedMotion) return;

    const timer = setTimeout(() => {
      const nextIdx = (currentIdx + 1) % PHASE_ORDER.length;
      setPhase(PHASE_ORDER[nextIdx] ?? "scanning");
    }, PHASE_DURATION_MS[phase]);

    return () => clearTimeout(timer);
  }, [currentIdx, isPlaying, phase, reducedMotion]);

  const handleTogglePlay = () => {
    if (isPlaying) {
      setIsPlaying(false);
      return;
    }
    if (phase === "done") {
      setPhase("scanning");
    }
    setIsPlaying(true);
  };

  const handleReset = () => {
    setIsPlaying(false);
    setPhase("scanning");
  };

  const handleSelectStage = (targetPhase: AnimationPhase) => {
    setIsPlaying(false);
    setPhase(targetPhase);
  };

  const fileTree: FileItem[] = [
    {
      name: "deep-search",
      type: "folder",
      indent: 0,
      highlight: phase === "scanning",
      active: ["load-skill", "load-template", "researching"].includes(phase),
      done: currentIdx >= phaseIndex("load-frontend"),
    },
    {
      name: "SKILL.md",
      type: "file",
      indent: 1,
      highlight: phase === "scanning",
      active: phase === "load-skill",
      done: currentIdx >= phaseIndex("load-template"),
    },
    {
      name: "biotech.md",
      type: "file",
      indent: 1,
      active: phase === "load-template",
      done: currentIdx >= phaseIndex("researching"),
    },
    {
      name: "computer-science.md",
      type: "file",
      indent: 1,
      skipped: currentIdx >= phaseIndex("researching"),
    },
    {
      name: "physics.md",
      type: "file",
      indent: 1,
      skipped: currentIdx >= phaseIndex("researching"),
    },
    {
      name: "frontend-design",
      type: "folder",
      indent: 0,
      highlight: phase === "scanning",
      active: ["load-frontend", "building"].includes(phase),
      done: currentIdx >= phaseIndex("load-deploy"),
    },
    {
      name: "SKILL.md",
      type: "file",
      indent: 1,
      highlight: phase === "scanning",
      active: phase === "load-frontend",
      done: currentIdx >= phaseIndex("building"),
    },
    {
      name: "deploy",
      type: "folder",
      indent: 0,
      highlight: phase === "scanning",
      active: ["load-deploy", "deploying"].includes(phase),
      done: phase === "done",
    },
    {
      name: "SKILL.md",
      type: "file",
      indent: 1,
      highlight: phase === "scanning",
      active: phase === "load-deploy",
      done: currentIdx >= phaseIndex("deploying"),
    },
    {
      name: "scripts",
      type: "folder",
      indent: 1,
      active: phase === "deploying",
      done: phase === "done",
    },
    {
      name: "deploy.sh",
      type: "file",
      indent: 2,
      active: phase === "deploying",
      done: phase === "done",
    },
  ];

  const activeStageId =
    currentIdx <= phaseIndex("scanning")
      ? "scan"
      : currentIdx <= phaseIndex("researching")
        ? "research"
        : currentIdx <= phaseIndex("building")
          ? "build"
          : "deploy";

  return (
    <div
      ref={containerRef}
      className={cn(
        "w-full min-w-0 overflow-hidden rounded-md border border-[var(--df-border)] bg-[var(--df-panel)]",
        className,
      )}
    >
      {/* Top Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--df-border)] bg-[var(--df-muted)]/65 px-4 py-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span
            className="size-2 shrink-0 rounded-full bg-[var(--df-accent)]"
            aria-hidden="true"
          />
          <span className="font-mono text-xs font-medium text-[var(--df-ink)]">
            {copy.agentLabel}
          </span>
          <span className="text-[var(--df-border-strong)]" aria-hidden="true">
            /
          </span>
          <span className="truncate font-mono text-xs text-[var(--df-accent)]">
            {copy.phaseStatus[phase]}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div
            className="flex flex-wrap items-center gap-1"
            role="group"
            aria-label="Skill loading stages"
          >
            {copy.stages.map((stage) => {
              const isSelected = stage.id === activeStageId;
              return (
                <button
                  key={stage.id}
                  type="button"
                  onClick={() => handleSelectStage(stage.phase)}
                  aria-pressed={isSelected}
                  className={cn(
                    "focus-visible:ring-ring/50 min-h-[32px] rounded border px-2.5 py-1 font-mono text-[11px] font-medium transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none",
                    isSelected
                      ? "border-[var(--df-cta)] bg-[var(--df-cta)] text-[var(--df-cta-fg)]"
                      : "border-[var(--df-border)] bg-[var(--df-panel)] text-[var(--df-muted-fg)] hover:border-[var(--df-accent)]/60 hover:text-[var(--df-ink)]",
                  )}
                >
                  {stage.label}
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleTogglePlay}
              aria-label={isPlaying ? copy.pause : copy.play}
              className="focus-visible:ring-ring/50 inline-flex min-h-[32px] items-center gap-1.5 rounded border border-[var(--df-border-strong)] bg-[var(--df-panel)] px-2.5 py-1 font-mono text-xs font-medium text-[var(--df-ink)] transition-colors duration-150 hover:border-[var(--df-accent)] hover:text-[var(--df-accent)] focus-visible:ring-2 focus-visible:outline-none"
            >
              {isPlaying ? (
                <Pause className="size-3.5" aria-hidden="true" />
              ) : (
                <Play className="size-3.5" aria-hidden="true" />
              )}
              <span>{isPlaying ? copy.pause : copy.play}</span>
            </button>

            <button
              type="button"
              onClick={handleReset}
              aria-label={copy.replay}
              className="focus-visible:ring-ring/50 inline-flex min-h-[32px] items-center justify-center rounded border border-[var(--df-border)] bg-[var(--df-panel)] px-2 py-1 text-[var(--df-muted-fg)] transition-colors duration-150 hover:border-[var(--df-accent)] hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none"
            >
              <RotateCcw className="size-3.5" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      {/* Main Split Content */}
      <div className="grid grid-cols-1 divide-y divide-[var(--df-border)] lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:divide-x lg:divide-y-0">
        {/* Left: Progressive File Tree */}
        <div className="min-w-0 bg-[var(--df-surface)] p-4 sm:p-6">
          <div className="mb-3 flex items-center justify-between gap-2 border-b border-[var(--df-border-soft)] pb-2.5">
            <span className="font-mono text-xs font-semibold text-[var(--df-accent)]">
              {copy.treeHeader}
            </span>
            <span className="font-mono text-[11px] text-[var(--df-muted-fg)]">
              progressive-load
            </span>
          </div>

          <ul className="space-y-1 font-mono text-xs sm:text-[13px]">
            {fileTree.map((item, index) => (
              <li
                key={`${item.name}-${index}`}
                className={cn(
                  "flex min-w-0 items-center justify-between gap-2 rounded px-2 py-1.5 transition-colors duration-150",
                  item.active
                    ? "bg-[color-mix(in_srgb,var(--df-accent)_12%,transparent)] font-medium text-[var(--df-accent)]"
                    : item.done
                      ? "text-[var(--df-ink)]"
                      : item.highlight
                        ? "bg-[var(--df-muted)] text-[var(--df-ink)]"
                        : "text-[var(--df-muted-fg)]",
                  item.skipped && "opacity-55",
                )}
                style={{ paddingLeft: `${item.indent * 16 + 8}px` }}
              >
                <span className="flex min-w-0 items-center gap-2">
                  {item.type === "folder" ? (
                    <Folder
                      className={cn(
                        "size-3.5 shrink-0",
                        item.active || item.done
                          ? "text-[var(--df-accent)]"
                          : "text-[var(--df-muted-fg)]",
                      )}
                      aria-hidden="true"
                    />
                  ) : (
                    <FileText
                      className={cn(
                        "size-3.5 shrink-0",
                        item.active
                          ? "text-[var(--df-accent)]"
                          : item.done
                            ? "text-emerald-700 dark:text-emerald-400"
                            : "text-[var(--df-muted-fg)]",
                      )}
                      aria-hidden="true"
                    />
                  )}
                  <span className="truncate">{item.name}</span>
                </span>

                {item.active && (
                  <span className="shrink-0 rounded border border-[var(--df-accent)]/40 px-1.5 py-0.5 text-[10px] text-[var(--df-accent)]">
                    {copy.loadingTag}
                  </span>
                )}
                {!item.active && item.done && item.type === "file" && (
                  <span className="inline-flex shrink-0 items-center gap-1 text-[10px] text-emerald-700 dark:text-emerald-400">
                    <Check className="size-3" aria-hidden="true" />
                    <span className="hidden sm:inline">{copy.loadedTag}</span>
                  </span>
                )}
                {item.skipped && (
                  <span className="shrink-0 text-[10px] text-[var(--df-muted-fg)]">
                    {copy.skippedTag}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>

        {/* Right: Execution Trace */}
        <div className="flex min-w-0 flex-col bg-[var(--df-panel)] p-4 sm:p-6">
          {/* Prompt Box */}
          <div className="rounded-md border border-[var(--df-border)] bg-[var(--df-surface)] p-3.5">
            <span className="font-mono text-[10px] font-semibold tracking-[0.18em] text-[var(--df-accent)] uppercase">
              {copy.promptBadge}
            </span>
            <p className="mt-1.5 text-sm leading-6 font-medium text-[var(--df-ink)]">
              {copy.promptText}
            </p>
          </div>

          {/* Progressive Execution Steps */}
          <div className="mt-4 flex-1 space-y-4 text-sm">
            <div className="flex items-center gap-2 font-mono text-xs text-[var(--df-muted-fg)]">
              <Check
                className="size-3.5 shrink-0 text-[var(--df-accent)]"
                aria-hidden="true"
              />
              <span>{copy.foundSkills}</span>
            </div>

            {currentIdx >= phaseIndex("load-skill") && (
              <div className="space-y-2 border-t border-[var(--df-border-soft)] pt-3">
                <p className="font-mono text-xs font-semibold text-[var(--df-ink)]">
                  {copy.researchingHeading}
                </p>
                <div className="flex items-center gap-2 font-mono text-xs text-[var(--df-muted-fg)]">
                  <FileText
                    className="size-3.5 shrink-0 text-[var(--df-accent)]"
                    aria-hidden="true"
                  />
                  <span>{copy.loadingDeepSearch}</span>
                </div>
                {currentIdx >= phaseIndex("load-template") && (
                  <div className="flex items-center gap-2 font-mono text-xs text-[var(--df-muted-fg)]">
                    <FileText
                      className="size-3.5 shrink-0 text-[var(--df-accent)]"
                      aria-hidden="true"
                    />
                    <span>{copy.loadingBiotech}</span>
                  </div>
                )}
                {currentIdx >= phaseIndex("researching") && (
                  <ul className="space-y-1 pt-1 pl-3">
                    {SEARCH_STEPS.map((step) => (
                      <li
                        key={step.text}
                        className="flex min-w-0 items-center gap-2 font-mono text-xs text-[var(--df-muted-fg)]"
                      >
                        {step.type === "search" ? (
                          <Search
                            className="size-3 shrink-0 text-[var(--df-accent)]"
                            aria-hidden="true"
                          />
                        ) : (
                          <Globe
                            className="size-3 shrink-0 text-emerald-700 dark:text-emerald-400"
                            aria-hidden="true"
                          />
                        )}
                        <span className="truncate">{step.text}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {currentIdx >= phaseIndex("load-frontend") && (
              <div className="space-y-2 border-t border-[var(--df-border-soft)] pt-3">
                <p className="font-mono text-xs font-semibold text-[var(--df-ink)]">
                  {copy.buildingHeading}
                </p>
                <div className="flex items-center gap-2 font-mono text-xs text-[var(--df-muted-fg)]">
                  <FileText
                    className="size-3.5 shrink-0 text-[var(--df-accent)]"
                    aria-hidden="true"
                  />
                  <span>{copy.loadingFrontend}</span>
                </div>
                {currentIdx >= phaseIndex("building") && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    {WORKSPACE_FILES.map((file) => (
                      <span
                        key={file}
                        className="inline-flex items-center gap-1.5 rounded border border-[var(--df-border)] bg-[var(--df-surface)] px-2 py-0.5 font-mono text-xs text-[var(--df-ink)]"
                      >
                        <Check
                          className="size-3 text-emerald-700 dark:text-emerald-400"
                          aria-hidden="true"
                        />
                        {copy.generatingPrefix} {file}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {currentIdx >= phaseIndex("load-deploy") && (
              <div className="space-y-2 border-t border-[var(--df-border-soft)] pt-3">
                <p className="font-mono text-xs font-semibold text-[var(--df-ink)]">
                  {copy.deployingHeading}
                </p>
                <div className="flex items-center gap-2 font-mono text-xs text-[var(--df-muted-fg)]">
                  <FileText
                    className="size-3.5 shrink-0 text-[var(--df-accent)]"
                    aria-hidden="true"
                  />
                  <span>{copy.loadingDeploy}</span>
                </div>
                {currentIdx >= phaseIndex("deploying") && (
                  <div className="flex items-center gap-2 font-mono text-xs text-[var(--df-muted-fg)]">
                    <Terminal
                      className="size-3.5 shrink-0 text-[var(--df-accent)]"
                      aria-hidden="true"
                    />
                    <span>{copy.executingDeploy}</span>
                  </div>
                )}
                {phase === "done" && (
                  <div className="mt-2 flex items-center gap-2 rounded-md border border-emerald-700/30 bg-emerald-700/10 px-3 py-2 font-mono text-xs font-medium text-emerald-800 dark:border-emerald-400/30 dark:text-emerald-300">
                    <Check className="size-4 shrink-0" aria-hidden="true" />
                    <span className="truncate">{copy.liveBanner}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
