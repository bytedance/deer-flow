import { describe, expect, it } from "@rstest/core";

import type { LocalSettings } from "@/core/settings";
import { buildRunContext } from "@/core/threads/hooks";

const settings = {
  mode: "pro",
  model_name: "gemma4",
  reasoning_effort: undefined,
} as unknown as LocalSettings["context"];

describe("buildRunContext", () => {
  it("sends attached references as a plain string[] under context.conversation_references", () => {
    const context = buildRunContext({
      settings,
      threadId: "t-1",
      extraContext: { agent_name: "writer" },
      conversationReferences: ["source-a", "source-b"],
    });
    expect(context.conversation_references).toEqual(["source-a", "source-b"]);
    expect(context.agent_name).toBe("writer");
    expect(context.thread_id).toBe("t-1");
    expect(context.is_plan_mode).toBe(true);
  });

  it("omits the key when nothing is attached, including on the replay path", () => {
    expect(
      "conversation_references" in
        buildRunContext({ settings, threadId: "t-1" }),
    ).toBe(false);
    expect(
      "conversation_references" in
        buildRunContext({
          settings,
          threadId: "t-1",
          conversationReferences: [],
        }),
    ).toBe(false);
  });

  it("never forwards a stray conversation_references key from local settings", () => {
    const stale = {
      ...settings,
      conversation_references: ["stale-source"],
    } as unknown as LocalSettings["context"];
    expect(
      "conversation_references" in
        buildRunContext({ settings: stale, threadId: "t-1" }),
    ).toBe(false);
    expect(
      buildRunContext({
        settings: stale,
        threadId: "t-1",
        conversationReferences: ["source-a"],
      }).conversation_references,
    ).toEqual(["source-a"]);
  });

  it("copies the list so later mutation of the caller's array cannot change the request", () => {
    const references = ["source-a"];
    const context = buildRunContext({
      settings,
      threadId: "t-1",
      conversationReferences: references,
    });
    references.push("source-b");
    expect(context.conversation_references).toEqual(["source-a"]);
  });
});
