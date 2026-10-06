/**
 * eval-metrics-overview.utils pure-function tests (spec 2026-08-24 §3.3/§3.4, plan Task 2).
 *
 * getProgressBarColor: Layer 2 卡片进度条三档着色（语义 CSS 变量）。
 * 单元格 delta/绝对裸色着色已退役（2026-09-06 分类行全中性），相应用例移除。
 */
import { describe, expect, it } from "@rstest/core";

import { classifyRagasSkipReason, getProgressBarColor } from "@/components/workspace/knowledge/eval-metrics-overview.utils";

describe("classifyRagasSkipReason", () => {
  // 后端 ragas_unavailable_reason() 的固定常量前缀；分类只认前缀，不整串比对。
  it("classifies the backend not-installed constant as not-installed", () => {
    expect(classifyRagasSkipReason("ragas 未安装（可选依赖；`uv sync --extra ragas` 后可用）")).toBe("not-installed");
  });

  it("treats a missing reason as not-installed (defensive)", () => {
    expect(classifyRagasSkipReason(null)).toBe("not-installed");
    expect(classifyRagasSkipReason(undefined)).toBe("not-installed");
  });

  it("classifies execution failures and empty output as runtime errors", () => {
    expect(classifyRagasSkipReason("ragas 执行失败: ConnectionError(...)")).toBe("error");
    expect(classifyRagasSkipReason("ragas 未产出结果")).toBe("error");
  });
});

describe("getProgressBarColor", () => {
  // 完整字面量类：Tailwind 静态扫描只认源码里逐字出现的候选类，
  // 运行时拼接 `variant:${utility}` 在生产构建不会生成 CSS 规则。
  it("returns the full muted class for null values (metric not produced)", () => {
    expect(getProgressBarColor(null)).toBe("[&_[data-slot=progress-indicator]]:bg-muted");
  });

  it("returns the full ok-tier class for values >= 0.8 (boundary inclusive)", () => {
    expect(getProgressBarColor(0.8)).toBe("[&_[data-slot=progress-indicator]]:bg-(--eval-ok)");
    expect(getProgressBarColor(0.97)).toBe("[&_[data-slot=progress-indicator]]:bg-(--eval-ok)");
  });

  it("returns the full warn-tier class for 0.6 <= value < 0.8", () => {
    expect(getProgressBarColor(0.6)).toBe("[&_[data-slot=progress-indicator]]:bg-(--eval-warn)");
    expect(getProgressBarColor(0.79)).toBe("[&_[data-slot=progress-indicator]]:bg-(--eval-warn)");
  });

  it("returns the full danger-tier class below 0.6", () => {
    expect(getProgressBarColor(0.59)).toBe("[&_[data-slot=progress-indicator]]:bg-(--eval-danger)");
    expect(getProgressBarColor(0)).toBe("[&_[data-slot=progress-indicator]]:bg-(--eval-danger)");
  });
});
