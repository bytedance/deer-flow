/**
 * Tests for the tool-streaming store (#4150).
 *
 * These import the production reducer and event mapper
 * (`applyToolStreamUpdate`, `toolStreamUpdateFromEvent`) — the exact
 * functions `ToolStreamingProvider` and `useThreadStream` execute — so a
 * regression in guard direction, partial accumulation, teardown, or
 * per-tool-call scoping (P1-2) fails here instead of passing vacuously.
 */
import { describe, expect, it } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  applyToolStreamUpdate,
  type ToolOutputChunkEvent,
  ToolStreamingProvider,
  toolStreamUpdateFromEvent,
  useToolCallStream,
  useToolStreaming,
} from "@/core/tasks/tool-streaming";
import type { ToolStreamOutput } from "@/core/tasks/types";

// ----------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------

function partial(text: string, toolName = "bash"): ToolStreamOutput {
  return { toolName, text, isPartial: true, isError: false };
}

function final(text: string, toolName = "bash"): ToolStreamOutput {
  return { toolName, text, isPartial: false, isError: false };
}

function chunkEvent(
  overrides: Partial<ToolOutputChunkEvent> = {},
): ToolOutputChunkEvent {
  return {
    type: "tool_output_chunk",
    tool_call_id: "tc-1",
    tool_name: "bash",
    chunk: "",
    is_partial: true,
    is_final: false,
    ...overrides,
  };
}

// ----------------------------------------------------------------
// applyToolStreamUpdate — the provider's production reducer
// ----------------------------------------------------------------

describe("applyToolStreamUpdate (production reducer)", () => {
  it("stores a start chunk and accumulates subsequent partial chunks", () => {
    let outputs = applyToolStreamUpdate({}, "tc-1", partial(""));
    outputs = applyToolStreamUpdate(outputs, "tc-1", partial("line1\n"));
    outputs = applyToolStreamUpdate(outputs, "tc-1", partial("line2"));
    expect(outputs["tc-1"]?.text).toBe("line1\nline2");
    expect(outputs["tc-1"]?.isPartial).toBe(true);
  });

  it("accepts the final chunk after the start/partial flow (guard is not inverted)", () => {
    // Regression for the #4150 blocker: the original guard rejected the
    // *final* chunk whenever a partial entry existed, so the completed
    // output never rendered and the spinner never stopped.
    let outputs = applyToolStreamUpdate({}, "tc-1", partial(""));
    outputs = applyToolStreamUpdate(outputs, "tc-1", final("complete output"));
    expect(outputs["tc-1"]?.text).toBe("complete output");
    expect(outputs["tc-1"]?.isPartial).toBe(false);
  });

  it("drops a late partial chunk after the final chunk", () => {
    const outputs = applyToolStreamUpdate({}, "tc-1", final("complete output"));
    const next = applyToolStreamUpdate(outputs, "tc-1", partial("stale"));
    expect(next).toBe(outputs); // no-op returns the same reference
    expect(next["tc-1"]?.text).toBe("complete output");
    expect(next["tc-1"]?.isPartial).toBe(false);
  });

  it("keys entries independently by tool_call_id (P1-2 scoping)", () => {
    let outputs = applyToolStreamUpdate({}, "tc-bash", partial("bash-output"));
    outputs = applyToolStreamUpdate(
      outputs,
      "tc-search",
      partial("search-output", "web_search"),
    );
    expect(outputs["tc-bash"]?.text).toBe("bash-output");
    expect(outputs["tc-search"]?.text).toBe("search-output");
    expect(Object.keys(outputs)).toHaveLength(2);

    // Removing one call's entry must not disturb the other.
    outputs = applyToolStreamUpdate(outputs, "tc-bash", null);
    expect("tc-bash" in outputs).toBe(false);
    expect(outputs["tc-search"]?.text).toBe("search-output");
  });

  it("removes an entry on null and no-ops for unknown ids", () => {
    const outputs = applyToolStreamUpdate({}, "tc-1", partial("text"));
    const removed = applyToolStreamUpdate(outputs, "tc-1", null);
    expect(Object.keys(removed)).toHaveLength(0);
    // Unknown id: same reference back, so the provider skips a render.
    expect(applyToolStreamUpdate(removed, "tc-unknown", null)).toBe(removed);
  });
});

// ----------------------------------------------------------------
// toolStreamUpdateFromEvent — the hooks.ts event mapping
// ----------------------------------------------------------------

describe("toolStreamUpdateFromEvent (event mapping and teardown)", () => {
  it("maps a start chunk to an empty partial entry", () => {
    const update = toolStreamUpdateFromEvent(chunkEvent());
    expect(update).toEqual({
      toolName: "bash",
      text: "",
      isPartial: true,
      isError: false,
    });
  });

  it("maps an intermediate partial chunk to its text", () => {
    const update = toolStreamUpdateFromEvent(chunkEvent({ chunk: "partial" }));
    expect(update?.text).toBe("partial");
    expect(update?.isPartial).toBe(true);
  });

  it("maps a final chunk to teardown (null)", () => {
    // The full result arrives via the canonical ToolMessage; keeping the
    // entry would leak one map entry per tool call for the whole thread.
    const update = toolStreamUpdateFromEvent(
      chunkEvent({ chunk: "preview", is_partial: false, is_final: true }),
    );
    expect(update).toBeNull();
  });

  it("maps an error chunk to teardown (null)", () => {
    const update = toolStreamUpdateFromEvent(
      chunkEvent({
        chunk: "boom",
        is_partial: false,
        is_final: true,
        error: true,
      }),
    );
    expect(update).toBeNull();
  });
});

// ----------------------------------------------------------------
// Provider rendering
// ----------------------------------------------------------------

function ToolCallStreamConsumer({ toolCallId }: { toolCallId: string }) {
  const stream = useToolCallStream(toolCallId);
  return createElement(
    "span",
    { "data-tool-call-id": toolCallId, "data-has-output": String(!!stream) },
    stream?.text ?? "(none)",
  );
}

function StreamingOutputsCount() {
  const { state } = useToolStreaming();
  const count = Object.keys(state.outputs).length;
  return createElement("span", { "data-output-count": count }, String(count));
}

describe("ToolStreamingProvider rendering", () => {
  it("renders children and initialises with zero outputs", () => {
    const html = renderToStaticMarkup(
      createElement(
        ToolStreamingProvider,
        null,
        createElement(StreamingOutputsCount),
      ),
    );
    expect(html).toContain('data-output-count="0"');
  });

  it("returns null for an unknown tool_call_id", () => {
    const html = renderToStaticMarkup(
      createElement(
        ToolStreamingProvider,
        null,
        createElement(ToolCallStreamConsumer, { toolCallId: "nonexistent" }),
      ),
    );
    expect(html).toContain('data-has-output="false"');
    expect(html).toContain("(none)");
  });
});
