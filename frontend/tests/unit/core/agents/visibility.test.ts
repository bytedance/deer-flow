import { describe, expect, it } from "vitest";

import { isAgentVisible } from "@/core/agents/hooks";
import type { Agent } from "@/core/agents/types";

function makeAgent(visibility?: Agent["visibility"]): Agent {
  return {
    name: "agent",
    description: "agent",
    display_name: "Agent",
    icon: null,
    visibility,
    model: null,
    tool_groups: null,
    skills: null,
    mcp_servers: null,
    tags: null,
    source: "builtin",
    editable: false,
    enabled: true,
  };
}

describe("isAgentVisible", () => {
  it("hides agents explicitly marked hidden", () => {
    expect(isAgentVisible(makeAgent("hidden"))).toBe(false);
  });

  it("keeps agents visible by default", () => {
    expect(isAgentVisible(makeAgent(undefined))).toBe(true);
    expect(isAgentVisible(makeAgent("public"))).toBe(true);
    expect(isAgentVisible(makeAgent(null))).toBe(true);
  });
});
