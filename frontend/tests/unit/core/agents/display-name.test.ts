import { expect, test } from "vitest";

import { getAgentDisplayName, hasAgentDisplayName } from "@/core/agents";

test("uses trimmed display name when present", () => {
  expect(
    getAgentDisplayName({
      name: "research-agent",
      display_name: "  Research Partner  ",
    }),
  ).toBe("Research Partner");
});

test("falls back to agent slug or explicit fallback when display name is blank", () => {
  expect(
    getAgentDisplayName({
      name: "research-agent",
      display_name: "   ",
    }),
  ).toBe("research-agent");

  expect(getAgentDisplayName(null, "fallback-agent")).toBe("fallback-agent");
});

test("detects whether an agent has a non-empty display name", () => {
  expect(hasAgentDisplayName({ display_name: " Agent " })).toBe(true);
  expect(hasAgentDisplayName({ display_name: "   " })).toBe(false);
  expect(hasAgentDisplayName({ display_name: null })).toBe(false);
});
