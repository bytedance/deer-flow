/**
 * Pure utility functions for eval metrics visualization (spec 2026-08-24 §3.3/§3.4).
 *
 * JSdom testable — no DOM dependencies. Align with vector-canvas/graph-utils patterns.
 */
export function getProgressBarColor(value: number | null | undefined): string {
  // Each composed candidate must appear verbatim: Tailwind's static scanner
  // cannot see dynamically interpolated `variant:${utility}` fragments, so a
  // runtime-composed class silently produces no production CSS rule. The
  // parent-scoped arbitrary variant targets ui/progress.tsx's indicator
  // without hand-editing the generated primitive.
  if (value == null) return "[&_[data-slot=progress-indicator]]:bg-muted";
  if (value >= 0.8) return "[&_[data-slot=progress-indicator]]:bg-(--eval-ok)";
  if (value >= 0.6) return "[&_[data-slot=progress-indicator]]:bg-(--eval-warn)";
  return "[&_[data-slot=progress-indicator]]:bg-(--eval-danger)";
}

/** 汇总行胶囊三档（2026-09-05）：与检索测试延时芯片同款胶囊与同色 trio
 *  （emerald/lime/orange 淡底 + 提亮文字），但按绝对值分档：≥0.9 / ≥0.8 / <0.8。
 *  汇总行颜色收进胶囊——不再走 delta/绝对文字着色（行字体不着色）。 */
export const SUMMARY_BAND_CLASSES = [
  "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  "bg-lime-500/10 text-lime-700 dark:text-lime-300",
  "bg-orange-500/10 text-orange-700 dark:text-orange-300",
] as const;

/** 汇总行胶囊档位：null 不着色（渲染破折号、无胶囊）。 */
export function getSummaryBandClass(value: number | null | undefined): string {
  if (value == null) return "";
  if (value >= 0.9) return SUMMARY_BAND_CLASSES[0];
  if (value >= 0.8) return SUMMARY_BAND_CLASSES[1];
  return SUMMARY_BAND_CLASSES[2];
}

export type RagasSkipKind = "not-installed" | "error";

/** Classify the backend `ragas_skip_reason` for badge copy selection. The
 * "未安装" prefix is the stable constant from harness `ragas_unavailable_reason()`;
 * everything else (execution failure, empty output) is a runtime error whose raw
 * text belongs in a tooltip, not the product header. */
export function classifyRagasSkipReason(reason: string | null | undefined): RagasSkipKind {
  if (!reason || reason.startsWith("ragas 未安装")) return "not-installed";
  return "error";
}
