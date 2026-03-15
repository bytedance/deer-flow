import type { AgentThreadContext } from "@/core/threads";

export type InputMode = "flash" | "thinking" | "pro" | "ultra";

export type InputBoxContext = Omit<
  AgentThreadContext,
  "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
> & {
  mode: InputMode | undefined;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
};

export function getResolvedMode(
  mode: InputMode | undefined,
  supportsThinking: boolean,
): InputMode {
  if (!supportsThinking && mode !== "flash") {
    return "flash";
  }
  if (mode) {
    return mode;
  }
  return supportsThinking ? "pro" : "flash";
}
