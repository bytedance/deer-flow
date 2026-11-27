"use client";

import {
  ArrowRight,
  Check,
  FileCode2,
  FolderOpen,
  Layers,
  Pause,
  Play,
  RotateCcw,
  Terminal,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { usePrefersReducedMotion } from "@/core/dom/render-activity";
import { DEFAULT_LOCALE, type Locale } from "@/core/i18n/locale";
import { cn } from "@/lib/utils";

type ProgressionStepId = "discover" | "load" | "execute";

const STEP_ORDER: readonly ProgressionStepId[] = [
  "discover",
  "load",
  "execute",
];

const STEP_DURATION_MS: Record<ProgressionStepId, number> = {
  discover: 2200,
  load: 2400,
  execute: 3200,
};

type SkillId = "deep-research" | "slide-deck" | "data-analysis" | "code-review";

type SkillSpec = {
  id: SkillId;
  manifestTokens: number;
  fullTokens: number;
  tagline: string;
  prompt: string;
  triggers: string[];
  templateFile: string;
  instructions: string[];
  command: string;
  outputs: string[];
  artifactPath: string;
};

type StepMeta = {
  id: ProgressionStepId;
  number: string;
  title: string;
  caption: string;
};

type InspectorCopy = {
  railAriaLabel: string;
  skillsListAriaLabel: string;
  mountPath: string;
  installedHeading: string;
  manifestOnlyLabel: string;
  loadedLabel: string;
  executingLabel: string;
  fullPromptSuffix: string;
  manifestSuffix: string;
  budgetTitle: string;
  budgetSavedPrefix: string;
  budgetSavedSuffix: string;
  eagerPrefix: string;
  play: string;
  pause: string;
  autoplayDisabledHint: string;
  reset: string;
  promptLabel: string;
  frontmatterHeading: string;
  instructionsHeading: string;
  sandboxHeading: string;
  onDemandHint: string;
  onDemandHintReducedMotion: string;
  executeHint: string;
  artifactDelivered: string;
  stepStatus: Record<ProgressionStepId, string>;
  steps: StepMeta[];
  skills: SkillSpec[];
};

const INSPECTOR_COPY: Record<Locale, InspectorCopy> = {
  "en-US": {
    railAriaLabel: "Skill loading progression steps",
    skillsListAriaLabel: "DeerFlow skills",
    mountPath: "/mnt/skills/",
    installedHeading: "Skill Registry",
    manifestOnlyLabel: "manifest",
    loadedLabel: "loaded",
    executingLabel: "running",
    fullPromptSuffix: "tok full",
    manifestSuffix: "~180 tokens",
    budgetTitle: "Context budget",
    budgetSavedPrefix: "Saved",
    budgetSavedSuffix: "vs eager load",
    eagerPrefix: "Eager all-skills:",
    play: "Play",
    pause: "Pause",
    autoplayDisabledHint: "Autoplay disabled when reduced motion is preferred",
    reset: "Reset",
    promptLabel: "MATCHED TASK",
    frontmatterHeading: "01 · YAML Frontmatter (always indexed)",
    instructionsHeading: "02 · On-Demand Instructions & References",
    sandboxHeading: "03 · Sandbox Execution Trace",
    onDemandHint:
      "Select step 02 or press Play to inject the full SKILL.md instructions.",
    onDemandHintReducedMotion:
      "Select step 02 to inject the full SKILL.md instructions.",
    executeHint:
      "Advance to step 03 to run bundled scripts inside the thread sandbox.",
    artifactDelivered: "Deliverable saved",
    stepStatus: {
      discover: "Scanning frontmatter",
      load: "Injecting matched SKILL.md",
      execute: "Running in sandbox",
    },
    steps: [
      {
        id: "discover",
        number: "01",
        title: "Discover Manifest",
        caption: "Index ~180 tokens of YAML metadata per skill.",
      },
      {
        id: "load",
        number: "02",
        title: "Load On-Demand",
        caption: "Read full SKILL.md & templates only on match.",
      },
      {
        id: "execute",
        number: "03",
        title: "Execute in Sandbox",
        caption: "Run bundled scripts and emit verified outputs.",
      },
    ],
    skills: [
      {
        id: "deep-research",
        manifestTokens: 180,
        fullTokens: 1420,
        tagline: "Multi-source synthesis & cited reports",
        prompt:
          "Compare open-source agent sandboxes and compile a cited engineering brief.",
        triggers: ["research", "citations", "literature", "brief"],
        templateFile: "references/citation-matrix.md",
        instructions: [
          "Decompose the query into 3–5 orthogonal sub-questions before searching.",
          "Cross-check claims across primary documentation and benchmark repos.",
          "Write structured findings with inline source links to outputs/report.md.",
        ],
        command: "python /mnt/skills/deep-research/scripts/verify_links.py",
        outputs: [
          "Verified 18 primary citations (0 broken)",
          "Compiled structured matrix (6 runtimes × 5 dimensions)",
        ],
        artifactPath: "/mnt/user-data/outputs/sandbox-brief.md",
      },
      {
        id: "slide-deck",
        manifestTokens: 175,
        fullTokens: 1180,
        tagline: "Structured narrative & HTML/PPTX decks",
        prompt:
          "Turn the Q3 architecture review notes into a 10-slide executive deck.",
        triggers: ["slides", "presentation", "deck", "pptx"],
        templateFile: "templates/editorial-grid.json",
        instructions: [
          "Outline one thesis per slide with max 35 words of body copy.",
          "Select matching visual layout blocks from editorial-grid.json.",
          "Render vector charts before assembling the final .pptx archive.",
        ],
        command:
          "node /mnt/skills/slide-deck/scripts/build_deck.mjs --theme warm",
        outputs: [
          "Rendered 10 slides with calibrated typography",
          "Embedded 3 SVG architecture diagrams",
        ],
        artifactPath: "/mnt/user-data/outputs/q3-architecture.pptx",
      },
      {
        id: "data-analysis",
        manifestTokens: 185,
        fullTokens: 1540,
        tagline: "Exploratory notebooks & visual charts",
        prompt:
          "Analyze churn drivers in subscriptions.csv and export cohort charts.",
        triggers: ["csv", "pandas", "cohort", "statistics"],
        templateFile: "references/chart-spec.md",
        instructions: [
          "Profile schema, missing values, and outlier quantiles before modeling.",
          "Compute cohort retention tables with confidence intervals.",
          "Export clean high-DPI PNG figures alongside a summary notebook.",
        ],
        command: "python /mnt/skills/data-analysis/scripts/cohort_report.py",
        outputs: [
          "Profiled 148,290 rows across 14 columns",
          "Generated retention_heatmap.png & summary.html",
        ],
        artifactPath: "/mnt/user-data/outputs/churn-analysis.html",
      },
      {
        id: "code-review",
        manifestTokens: 170,
        fullTokens: 1060,
        tagline: "Diff auditing, test gaps & risk checks",
        prompt:
          "Audit the sandbox provisioner PR for concurrency and cleanup bugs.",
        triggers: ["review", "diff", "audit", "regression"],
        templateFile: "checklists/async-safety.md",
        instructions: [
          "Inspect state transitions, timeout cleanup, and error propagation.",
          "Flag blocking I/O or leaked handles on async request paths.",
          "Propose minimal reproduction tests for every high-severity finding.",
        ],
        command: "python /mnt/skills/code-review/scripts/scan_diff.py --strict",
        outputs: [
          "Checked 12 changed modules against async-safety.md",
          "Flagged 2 lifecycle edge cases with patch suggestions",
        ],
        artifactPath: "/mnt/user-data/outputs/review-summary.md",
      },
    ],
  },
  "zh-CN": {
    railAriaLabel: "技能加载三阶段进度",
    skillsListAriaLabel: "DeerFlow 技能列表",
    mountPath: "/mnt/skills/",
    installedHeading: "技能注册表",
    manifestOnlyLabel: "仅清单",
    loadedLabel: "已加载",
    executingLabel: "执行中",
    fullPromptSuffix: "tok 完整",
    manifestSuffix: "~180 tokens",
    budgetTitle: "上下文 Token 预算",
    budgetSavedPrefix: "节省",
    budgetSavedSuffix: "（对比全量加载）",
    eagerPrefix: "全量加载开销：",
    play: "播放",
    pause: "暂停",
    autoplayDisabledHint: "已开启减少动态效果，自动播放已禁用",
    reset: "重置",
    promptLabel: "命中任务",
    frontmatterHeading: "01 · YAML 元数据清单（始终常驻索引）",
    instructionsHeading: "02 · 按需注入的技能指令与参考模板",
    sandboxHeading: "03 · 沙箱执行轨迹",
    onDemandHint: "点击步骤 02 或播放按钮，查看完整 SKILL.md 按需注入效果。",
    onDemandHintReducedMotion: "点击步骤 02，查看完整 SKILL.md 按需注入效果。",
    executeHint: "切换至步骤 03，查看在会话沙箱中运行内置脚本与产物交付。",
    artifactDelivered: "交付物已生成",
    stepStatus: {
      discover: "扫描前置元数据",
      load: "按需注入 SKILL.md",
      execute: "沙箱内执行脚本",
    },
    steps: [
      {
        id: "discover",
        number: "01",
        title: "扫描技能清单",
        caption: "每个技能仅索引约 180 tokens 的 YAML 元数据。",
      },
      {
        id: "load",
        number: "02",
        title: "按需加载上下文",
        caption: "仅在任务命中时读取完整 SKILL.md 与模板。",
      },
      {
        id: "execute",
        number: "03",
        title: "沙箱内执行交付",
        caption: "运行配套脚本并在隔离目录输出可验证成果。",
      },
    ],
    skills: [
      {
        id: "deep-research",
        manifestTokens: 180,
        fullTokens: 1420,
        tagline: "多源交叉检索与可溯源研究报告",
        prompt: "对比主流开源 Agent 沙箱方案，输出带引用来源的工程评估报告。",
        triggers: ["research", "citations", "literature", "brief"],
        templateFile: "references/citation-matrix.md",
        instructions: [
          "先将研究目标拆解为 3–5 个正交子问题再并行检索。",
          "优先核对官方文档与基准测试仓库，避免二手转述偏差。",
          "附带行内引用链接输出结构化报告至 outputs/report.md。",
        ],
        command: "python /mnt/skills/deep-research/scripts/verify_links.py",
        outputs: [
          "已校验 18 条一手引用链接（0 失效）",
          "已生成 6 种运行时 × 5 个维度的对比矩阵",
        ],
        artifactPath: "/mnt/user-data/outputs/sandbox-brief.md",
      },
      {
        id: "slide-deck",
        manifestTokens: 175,
        fullTokens: 1180,
        tagline: "结构化叙事与 HTML/PPTX 演示文稿",
        prompt: "将 Q3 架构评审记录整理为 10 页高管汇报演示文稿。",
        triggers: ["slides", "presentation", "deck", "pptx"],
        templateFile: "templates/editorial-grid.json",
        instructions: [
          "每页仅聚焦一个核心论点，正文控制在精炼要点内。",
          "依据 editorial-grid.json 匹配信息密度与版式网格。",
          "先渲染矢量图表，再打包生成可编辑 .pptx 交付文件。",
        ],
        command:
          "node /mnt/skills/slide-deck/scripts/build_deck.mjs --theme warm",
        outputs: ["已渲染 10 页统一排版演示文稿", "已嵌入 3 张 SVG 架构示意图"],
        artifactPath: "/mnt/user-data/outputs/q3-architecture.pptx",
      },
      {
        id: "data-analysis",
        manifestTokens: 185,
        fullTokens: 1540,
        tagline: "探索性数据分析与可视化图表",
        prompt: "分析 subscriptions.csv 中的用户流失驱动因素并输出留存图表。",
        triggers: ["csv", "pandas", "cohort", "statistics"],
        templateFile: "references/chart-spec.md",
        instructions: [
          "建模前先完成字段分布、缺失值与异常分位检查。",
          "按队列计算留存率曲线及显著性置信区间。",
          "导出高分辨率图表与可交互分析报告 HTML。",
        ],
        command: "python /mnt/skills/data-analysis/scripts/cohort_report.py",
        outputs: [
          "已分析 148,290 行 × 14 列订阅记录",
          "已生成 retention_heatmap.png 与 summary.html",
        ],
        artifactPath: "/mnt/user-data/outputs/churn-analysis.html",
      },
      {
        id: "code-review",
        manifestTokens: 170,
        fullTokens: 1060,
        tagline: "变更审计、并发风险与测试缺口定位",
        prompt: "审查沙箱调度器 PR 中的异步并发与资源释放隐患。",
        triggers: ["review", "diff", "audit", "regression"],
        templateFile: "checklists/async-safety.md",
        instructions: [
          "逐项检查状态机迁移、超时回收与异常传播路径。",
          "排查异步请求链路中的阻塞 I/O 与未关闭句柄。",
          "针对每条高危问题给出最小复现测试与修复建议。",
        ],
        command: "python /mnt/skills/code-review/scripts/scan_diff.py --strict",
        outputs: [
          "已按 async-safety.md 扫描 12 个变更模块",
          "定位 2 处生命周期边界问题并附修复补丁",
        ],
        artifactPath: "/mnt/user-data/outputs/review-summary.md",
      },
    ],
  },
};

export default function ProgressiveSkillsAnimation({
  locale = DEFAULT_LOCALE,
  className,
}: {
  locale?: Locale;
  className?: string;
}) {
  const copy = INSPECTOR_COPY[locale] ?? INSPECTOR_COPY["en-US"];
  const reducedMotion = usePrefersReducedMotion();
  const [activeStep, setActiveStep] = useState<ProgressionStepId>("load");
  const [selectedSkillId, setSelectedSkillId] =
    useState<SkillId>("deep-research");
  const [isPlaying, setIsPlaying] = useState(false);
  const [hasAutoPlayed, setHasAutoPlayed] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const stepIndex = STEP_ORDER.indexOf(activeStep);
  const selectedSkill =
    copy.skills.find((skill) => skill.id === selectedSkillId) ??
    copy.skills[0]!;

  const totalManifestTokens = copy.skills.reduce(
    (sum, skill) => sum + skill.manifestTokens,
    0,
  );
  const totalEagerTokens = copy.skills.reduce(
    (sum, skill) => sum + skill.fullTokens,
    0,
  );
  const activeTokens =
    stepIndex === 0
      ? totalManifestTokens
      : totalManifestTokens -
        selectedSkill.manifestTokens +
        selectedSkill.fullTokens;
  const savedPercent = Math.round(
    ((totalEagerTokens - activeTokens) / totalEagerTokens) * 100,
  );
  const usageWidthPercent = Math.min(
    100,
    Math.max(12, Math.round((activeTokens / totalEagerTokens) * 100)),
  );

  useEffect(() => {
    if (reducedMotion) {
      setIsPlaying(false);
      setActiveStep("execute");
      return;
    }
    if (hasAutoPlayed || !containerRef.current) return;
    if (typeof IntersectionObserver === "undefined") return;

    const element = containerRef.current;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setHasAutoPlayed(true);
          setActiveStep("discover");
          setIsPlaying(true);
        }
      },
      { threshold: 0.25 },
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, [hasAutoPlayed, reducedMotion]);

  useEffect(() => {
    if (!isPlaying || reducedMotion) return;

    const timer = setTimeout(() => {
      const nextIdx = (stepIndex + 1) % STEP_ORDER.length;
      setActiveStep(STEP_ORDER[nextIdx] ?? "discover");
    }, STEP_DURATION_MS[activeStep]);

    return () => clearTimeout(timer);
  }, [activeStep, isPlaying, reducedMotion, stepIndex]);

  const handleSelectStep = (step: ProgressionStepId) => {
    setIsPlaying(false);
    setActiveStep(step);
  };

  const handleSelectSkill = (skillId: SkillId) => {
    setIsPlaying(false);
    setSelectedSkillId(skillId);
  };

  const effectiveIsPlaying = !reducedMotion && isPlaying;

  const handleTogglePlay = () => {
    if (reducedMotion) return;
    if (isPlaying) {
      setIsPlaying(false);
      return;
    }
    if (activeStep === "execute") {
      setActiveStep("discover");
    }
    setIsPlaying(true);
  };

  const handleReset = () => {
    setIsPlaying(false);
    setActiveStep("discover");
    setSelectedSkillId("deep-research");
  };

  return (
    <div
      ref={containerRef}
      className={cn("w-full min-w-0 space-y-6", className)}
    >
      {/* Horizontal 3-Step Progression Rail */}
      <div
        role="group"
        aria-label={copy.railAriaLabel}
        className="grid grid-cols-1 gap-3 md:grid-cols-3 md:gap-4"
      >
        {copy.steps.map((step, idx) => {
          const isCurrent = step.id === activeStep;
          const isCompleted = idx < stepIndex;

          return (
            <button
              key={step.id}
              type="button"
              onClick={() => handleSelectStep(step.id)}
              aria-pressed={isCurrent}
              className={cn(
                "group focus-visible:ring-ring/50 relative flex min-w-0 flex-col rounded-xl border p-4 text-left transition-all duration-200 focus-visible:ring-2 focus-visible:outline-none sm:p-5",
                isCurrent
                  ? "border-[var(--df-accent)]/60 bg-[var(--df-panel)] shadow-[0_8px_22px_var(--df-shadow)]"
                  : "border-[var(--df-border)] bg-[var(--df-surface)] hover:border-[var(--df-border-strong)] hover:bg-[var(--df-panel)]",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span
                  className={cn(
                    "inline-flex size-7 shrink-0 items-center justify-center rounded-full font-mono text-xs font-semibold tabular-nums transition-colors duration-150",
                    isCurrent
                      ? "bg-[var(--df-cta)] text-[var(--df-cta-fg)]"
                      : isCompleted
                        ? "bg-[var(--df-accent-soft,rgba(28,93,74,0.09))] text-[var(--df-accent)]"
                        : "border border-[var(--df-border-strong)] bg-[var(--df-panel)] text-[var(--df-muted-fg)]",
                  )}
                >
                  {isCompleted ? (
                    <Check className="size-3.5" aria-hidden="true" />
                  ) : (
                    step.number
                  )}
                </span>

                {idx < copy.steps.length - 1 && (
                  <ArrowRight
                    className={cn(
                      "hidden size-4 shrink-0 md:block",
                      isCurrent || isCompleted
                        ? "text-[var(--df-accent)]"
                        : "text-[var(--df-border-strong)]",
                    )}
                    aria-hidden="true"
                  />
                )}
              </div>

              <p className="mt-3 text-sm font-semibold text-[var(--df-ink)] sm:text-base">
                {step.number} {step.title}
              </p>
              <p className="mt-1 text-xs leading-5 text-[var(--df-muted-fg)] sm:text-sm">
                {step.caption}
              </p>
            </button>
          );
        })}
      </div>

      {/* 2-Pane Skill Inspector */}
      <div className="w-full min-w-0 overflow-hidden rounded-2xl border border-[var(--df-border)] bg-[var(--df-panel)] shadow-[0_8px_26px_var(--df-shadow)]">
        {/* Inspector Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--df-border)] bg-[var(--df-bg-soft)] px-4 py-3 sm:px-6">
          <div className="flex min-w-0 flex-wrap items-center gap-2.5">
            <span
              className="size-2 shrink-0 rounded-full bg-[var(--df-accent)]"
              aria-hidden="true"
            />
            <span className="font-mono text-xs font-semibold text-[var(--df-ink)]">
              {copy.mountPath}
            </span>
            <span className="text-[var(--df-border-strong)]" aria-hidden="true">
              /
            </span>
            <span className="truncate font-mono text-xs text-[var(--df-accent)]">
              {copy.stepStatus[activeStep]}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--df-accent-soft,rgba(28,93,74,0.09))] px-3 py-1 font-mono text-[11px] font-medium text-[var(--df-accent)] tabular-nums">
              <Layers className="size-3 shrink-0" aria-hidden="true" />
              <span>
                {activeTokens.toLocaleString()} /{" "}
                {totalEagerTokens.toLocaleString()} tok
              </span>
            </span>

            <button
              type="button"
              disabled={reducedMotion}
              onClick={handleTogglePlay}
              title={reducedMotion ? copy.autoplayDisabledHint : undefined}
              aria-label={
                reducedMotion
                  ? copy.autoplayDisabledHint
                  : effectiveIsPlaying
                    ? copy.pause
                    : copy.play
              }
              className={cn(
                "focus-visible:ring-ring/50 inline-flex min-h-[34px] items-center gap-1.5 rounded-full px-3.5 py-1 font-mono text-xs font-medium transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-45",
                effectiveIsPlaying
                  ? "bg-[var(--df-cta)] text-[var(--df-cta-fg)] hover:bg-[var(--df-cta-hover)]"
                  : "border border-[var(--df-border-strong)] bg-[var(--df-panel)] text-[var(--df-ink)] enabled:hover:border-[var(--df-accent)] enabled:hover:text-[var(--df-accent)]",
              )}
            >
              {effectiveIsPlaying ? (
                <Pause className="size-3.5" aria-hidden="true" />
              ) : (
                <Play className="size-3.5" aria-hidden="true" />
              )}
              <span>{effectiveIsPlaying ? copy.pause : copy.play}</span>
            </button>

            <button
              type="button"
              onClick={handleReset}
              aria-label={copy.reset}
              className="focus-visible:ring-ring/50 inline-flex min-h-[34px] items-center justify-center rounded-full border border-[var(--df-border)] bg-[var(--df-panel)] px-2.5 py-1 text-[var(--df-muted-fg)] transition-colors duration-150 hover:border-[var(--df-accent)] hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none"
            >
              <RotateCcw className="size-3.5" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Split Body */}
        <div className="grid grid-cols-1 divide-y divide-[var(--df-border)] lg:grid-cols-12 lg:divide-x lg:divide-y-0">
          {/* Left Pane: Interactive Skill Registry & Token Budget */}
          <div className="flex min-w-0 flex-col justify-between bg-[var(--df-surface)] p-4 sm:p-6 lg:col-span-5">
            <div>
              <div className="mb-3 flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] font-semibold tracking-[0.16em] text-[var(--df-muted-fg)] uppercase">
                  {copy.installedHeading}
                </span>
                <span className="font-mono text-[11px] text-[var(--df-accent)]">
                  {copy.manifestSuffix}
                </span>
              </div>

              <div
                role="group"
                aria-label={copy.skillsListAriaLabel}
                className="space-y-2"
              >
                {copy.skills.map((skill) => {
                  const isSelected = skill.id === selectedSkill.id;
                  const isFullLoaded = isSelected && stepIndex >= 1;
                  const isRunning = isSelected && stepIndex === 2;

                  return (
                    <button
                      key={skill.id}
                      type="button"
                      onClick={() => handleSelectSkill(skill.id)}
                      aria-pressed={isSelected}
                      className={cn(
                        "focus-visible:ring-ring/50 flex w-full min-w-0 flex-col rounded-xl border p-3.5 text-left transition-all duration-150 focus-visible:ring-2 focus-visible:outline-none",
                        isSelected
                          ? "border-[var(--df-accent)]/60 bg-[var(--df-panel)] shadow-[0_4px_14px_var(--df-shadow)]"
                          : "border-[var(--df-border-soft)] bg-[var(--df-panel)]/65 hover:border-[var(--df-border-strong)] hover:bg-[var(--df-panel)]",
                      )}
                    >
                      <div className="flex w-full min-w-0 items-center justify-between gap-2">
                        <span className="flex min-w-0 items-center gap-2 font-mono text-xs font-semibold text-[var(--df-ink)]">
                          <FolderOpen
                            className={cn(
                              "size-3.5 shrink-0",
                              isSelected
                                ? "text-[var(--df-accent)]"
                                : "text-[var(--df-muted-fg)]",
                            )}
                            aria-hidden="true"
                          />
                          <span className="truncate">{skill.id}</span>
                        </span>

                        <span
                          className={cn(
                            "shrink-0 rounded-full px-2 py-0.5 font-mono text-[10px] font-medium",
                            isRunning
                              ? "bg-[var(--df-cta)] text-[var(--df-cta-fg)]"
                              : isFullLoaded
                                ? "bg-[var(--df-accent-soft,rgba(28,93,74,0.09))] text-[var(--df-accent)]"
                                : "border border-[var(--df-border)] bg-[var(--df-surface)] text-[var(--df-muted-fg)]",
                          )}
                        >
                          {isRunning
                            ? copy.executingLabel
                            : isFullLoaded
                              ? copy.loadedLabel
                              : copy.manifestOnlyLabel}
                        </span>
                      </div>

                      <p className="mt-1.5 text-xs leading-5 text-[var(--df-muted-fg)]">
                        {skill.tagline}
                      </p>

                      <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 font-mono text-[11px] tabular-nums">
                        <span className="text-[var(--df-text-soft)]">
                          {isFullLoaded
                            ? `${skill.fullTokens.toLocaleString()} tok`
                            : `~${skill.manifestTokens} tok`}
                        </span>
                        <span className="text-[var(--df-muted-fg)]">
                          {skill.fullTokens.toLocaleString()}{" "}
                          {copy.fullPromptSuffix}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Context Budget Savings Card */}
            <div className="mt-5 rounded-xl border border-[var(--df-border)] bg-[var(--df-panel)] p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-[11px] font-semibold tracking-[0.12em] text-[var(--df-ink)] uppercase">
                  {copy.budgetTitle}
                </span>
                <span className="rounded-full bg-[var(--df-accent-soft,rgba(28,93,74,0.09))] px-2.5 py-0.5 font-mono text-[11px] font-semibold text-[var(--df-accent)] tabular-nums">
                  {copy.budgetSavedPrefix} {savedPercent}%{" "}
                  {copy.budgetSavedSuffix}
                </span>
              </div>

              <div
                className="mt-3 h-2 w-full overflow-hidden rounded-full bg-[var(--df-muted)]"
                aria-hidden="true"
              >
                <div
                  className="h-full rounded-full bg-[var(--df-cta)] transition-all duration-300"
                  style={{ width: `${usageWidthPercent}%` }}
                />
              </div>

              <p className="mt-2 font-mono text-[11px] text-[var(--df-muted-fg)] tabular-nums">
                {copy.eagerPrefix} {totalEagerTokens.toLocaleString()} tok
              </p>
            </div>
          </div>

          {/* Right Pane: YAML Frontmatter & Execution Inspector */}
          <div className="flex min-w-0 flex-col bg-[var(--df-panel)] p-4 sm:p-6 lg:col-span-7">
            {/* Active Prompt Context */}
            <div className="rounded-xl border border-[var(--df-border)] bg-[var(--df-surface)] p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-[10px] font-semibold tracking-[0.18em] text-[var(--df-accent)] uppercase">
                  {copy.promptLabel}
                </span>
                <span className="font-mono text-[11px] text-[var(--df-muted-fg)]">
                  /mnt/skills/{selectedSkill.id}/SKILL.md
                </span>
              </div>
              <p className="mt-1.5 text-sm leading-6 font-medium text-[var(--df-ink)]">
                {selectedSkill.prompt}
              </p>
            </div>

            {/* Step 01: YAML Frontmatter */}
            <div className="mt-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="flex items-center gap-1.5 font-mono text-xs font-semibold text-[var(--df-ink)]">
                  <FileCode2
                    className="size-3.5 shrink-0 text-[var(--df-accent)]"
                    aria-hidden="true"
                  />
                  <span>{copy.frontmatterHeading}</span>
                </p>
                <span className="font-mono text-[11px] text-[var(--df-accent)] tabular-nums">
                  ~{selectedSkill.manifestTokens} tok
                </span>
              </div>

              <pre className="mt-2.5 overflow-x-auto rounded-xl border border-[var(--df-border-soft)] bg-[var(--df-bg-soft)] p-3.5 font-mono text-xs leading-6 text-[var(--df-text-soft)]">
                <code>{`---\nname: ${selectedSkill.id}\ntriggers: [${selectedSkill.triggers.join(", ")}]\nreference: ${selectedSkill.templateFile}\n---`}</code>
              </pre>
            </div>

            {/* Step 02: On-Demand Instructions */}
            <div className="mt-5 border-t border-[var(--df-border-soft)] pt-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-mono text-xs font-semibold text-[var(--df-ink)]">
                  {copy.instructionsHeading}
                </p>
                {stepIndex >= 1 && (
                  <span className="font-mono text-[11px] text-[var(--df-accent)] tabular-nums">
                    +{selectedSkill.fullTokens - selectedSkill.manifestTokens}{" "}
                    tok
                  </span>
                )}
              </div>

              {stepIndex >= 1 ? (
                <div className="mt-2.5 space-y-2 rounded-xl border border-[var(--df-border-soft)] bg-[var(--df-surface)] p-4">
                  <div className="inline-flex items-center gap-1.5 rounded-md border border-[var(--df-border)] bg-[var(--df-panel)] px-2 py-0.5 font-mono text-[11px] text-[var(--df-accent)]">
                    <Check className="size-3 shrink-0" aria-hidden="true" />
                    <span>{selectedSkill.templateFile}</span>
                  </div>
                  <ol className="space-y-1.5 pt-1 text-xs leading-6 text-[var(--df-text-soft)] sm:text-sm">
                    {selectedSkill.instructions.map((line, index) => (
                      <li key={line} className="flex gap-2">
                        <span className="shrink-0 font-mono text-xs font-semibold text-[var(--df-accent)] tabular-nums">
                          {index + 1}.
                        </span>
                        <span>{line}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              ) : (
                <p className="mt-2 text-xs leading-6 text-[var(--df-muted-fg)]">
                  {reducedMotion
                    ? copy.onDemandHintReducedMotion
                    : copy.onDemandHint}
                </p>
              )}
            </div>

            {/* Step 03: Sandbox Execution */}
            <div className="mt-5 border-t border-[var(--df-border-soft)] pt-4">
              <p className="flex items-center gap-1.5 font-mono text-xs font-semibold text-[var(--df-ink)]">
                <Terminal
                  className="size-3.5 shrink-0 text-[var(--df-accent)]"
                  aria-hidden="true"
                />
                <span>{copy.sandboxHeading}</span>
              </p>

              {stepIndex >= 2 ? (
                <div className="mt-2.5 space-y-3">
                  <pre className="overflow-x-auto rounded-xl border border-[var(--df-border-soft)] bg-[var(--df-bg-soft)] p-3.5 font-mono text-xs leading-6">
                    <code className="block space-y-1">
                      <div className="flex gap-2">
                        <span
                          className="shrink-0 font-semibold text-[var(--df-accent)] select-none"
                          aria-hidden="true"
                        >
                          $
                        </span>
                        <span className="font-medium text-[var(--df-ink)]">
                          {selectedSkill.command}
                        </span>
                      </div>
                      {selectedSkill.outputs.map((line) => (
                        <div
                          key={line}
                          className="pl-4 text-emerald-700 dark:text-emerald-400"
                        >
                          ✔ {line}
                        </div>
                      ))}
                    </code>
                  </pre>

                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--df-accent)]/35 bg-[var(--df-accent-soft,rgba(28,93,74,0.09))] px-3.5 py-2.5 font-mono text-xs text-[var(--df-accent)]">
                    <span className="inline-flex items-center gap-1.5 font-medium">
                      <Check className="size-3.5 shrink-0" aria-hidden="true" />
                      <span>{copy.artifactDelivered}</span>
                    </span>
                    <span className="truncate font-semibold">
                      {selectedSkill.artifactPath}
                    </span>
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-xs leading-6 text-[var(--df-muted-fg)]">
                  {copy.executeHint}
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
