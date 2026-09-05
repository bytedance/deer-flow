import type { LocalSettings } from "../settings";

export function buildThreadModeContext(context: LocalSettings["context"]) {
  return {
    thinking_enabled: context.mode !== "flash",
    is_plan_mode: context.mode === "pro" || context.mode === "ultra",
    ...(context.mode === "ultra" ? { subagent_enabled: true } : {}),
    reasoning_effort:
      context.reasoning_effort ??
      (context.mode === "ultra"
        ? "high"
        : context.mode === "pro"
          ? "medium"
          : context.mode === "thinking"
            ? "low"
            : undefined),
  };
}
