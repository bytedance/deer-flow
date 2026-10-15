import type { Message } from "@langchain/langgraph-sdk";
import { describe, expect, test } from "@rstest/core";

import { getMessageGroups } from "@/core/messages/utils";
import { getWorkspaceChangeAnchorGroupIndices } from "@/core/messages/workspace-change-anchor";

function message(
  id: string,
  type: Message["type"],
  content: string,
  runId?: string,
): Message {
  return {
    id,
    type,
    content,
    ...(runId ? { run_id: runId } : {}),
  } as Message;
}

function toolCall(id: string, runId: string, callId: string): Message {
  return {
    ...message(id, "ai", "", runId),
    tool_calls: [{ id: callId, name: "write_file", args: {} }],
  } as Message;
}

function toolResult(id: string, runId: string, callId: string): Message {
  return {
    ...message(id, "tool", "ok", runId),
    tool_call_id: callId,
  } as Message;
}

describe("workspace change card placement", () => {
  test("anchors one card on the run's last assistant bubble", () => {
    // A settled run whose model emitted answer text mid-run that never gained a
    // tool call: two terminal assistant bubbles share one run_id (#4555).
    const groups = getMessageGroups([
      message("human-1", "human", "Update the config"),
      message("ai-middle", "ai", "Let me check the repo first.", "run-1"),
      toolCall("ai-tool-1", "run-1", "call-1"),
      toolResult("tool-1", "run-1", "call-1"),
      message("ai-final", "ai", "Done. I updated two files.", "run-1"),
    ]);

    expect(groups.map((group) => group.type)).toEqual([
      "human",
      "assistant",
      "assistant:processing",
      "assistant",
    ]);
    expect([...getWorkspaceChangeAnchorGroupIndices(groups)]).toEqual([3]);
  });

  test("anchors one card per run across consecutive turns", () => {
    const groups = getMessageGroups([
      message("human-1", "human", "First task"),
      message("ai-1-middle", "ai", "Working on it.", "run-1"),
      message("ai-1-final", "ai", "First answer", "run-1"),
      message("human-2", "human", "Second task"),
      message("ai-2-final", "ai", "Second answer", "run-2"),
    ]);

    expect([...getWorkspaceChangeAnchorGroupIndices(groups)]).toEqual([2, 4]);
  });

  test("ignores groups that never render the card", () => {
    // Processing groups hold the tool steps and carry the same run_id, but the
    // card is rendered only by terminal assistant bubbles.
    const groups = getMessageGroups([
      message("human-1", "human", "Just run a tool"),
      toolCall("ai-tool-1", "run-1", "call-1"),
      toolResult("tool-1", "run-1", "call-1"),
    ]);

    expect(getWorkspaceChangeAnchorGroupIndices(groups).size).toBe(0);
  });

  test("skips assistant bubbles without a run id", () => {
    // The card resolves from (threadId, runId); a bubble with no run_id cannot
    // fetch one and must not claim the anchor.
    const groups = getMessageGroups([
      message("human-1", "human", "Hello"),
      message("ai-final", "ai", "Hi there"),
    ]);

    expect(getWorkspaceChangeAnchorGroupIndices(groups).size).toBe(0);
  });

  test("keeps the streaming bubble anchored while the turn is still loading", () => {
    // Mid-stream a content-only message stays in the processing group, so the
    // run has no terminal bubble yet and no card position.
    const messages = [
      message("human-1", "human", "Update the config"),
      message("ai-middle", "ai", "Let me check the repo first.", "run-1"),
    ];

    const streaming = getMessageGroups(messages, {
      isCurrentTurnLoading: true,
    });
    expect(getWorkspaceChangeAnchorGroupIndices(streaming).size).toBe(0);

    const settled = getMessageGroups([
      ...messages,
      message("ai-final", "ai", "Done.", "run-1"),
    ]);
    expect([...getWorkspaceChangeAnchorGroupIndices(settled)]).toEqual([2]);
  });
});
