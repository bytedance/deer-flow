import { describe, expect, it } from "@rstest/core";

import { buildThreadModeContext } from "@/core/threads/run-context";

describe("buildThreadModeContext", () => {
  it("enables subagents explicitly for ultra mode", () => {
    expect(
      buildThreadModeContext({
        mode: "ultra",
        model_name: undefined,
      }),
    ).toMatchObject({
      thinking_enabled: true,
      is_plan_mode: true,
      subagent_enabled: true,
      reasoning_effort: "high",
    });
  });

  it("leaves subagent selection unset for other modes", () => {
    for (const mode of ["flash", "thinking", "pro", undefined] as const) {
      expect(
        buildThreadModeContext({
          mode,
          model_name: undefined,
        }),
      ).not.toHaveProperty("subagent_enabled");
    }
  });
});
