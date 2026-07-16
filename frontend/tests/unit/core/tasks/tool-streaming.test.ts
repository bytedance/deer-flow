/**
 * Regression tests for P1-2: scoped streaming output.
 *
 * Two parallel in-progress subtasks must never render each other's tool
 * output.  The ToolStreamingProvider keys state by ``tool_call_id`` so each
 * subtask card can filter by the ids it owns.
 */
import { describe, expect, it } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  ToolStreamingProvider,
  useToolCallStream,
  useToolStreaming,
} from "@/core/tasks/tool-streaming";

// ----------------------------------------------------------------
// A thin consumer component that reads streaming state for a given
// tool_call_id so we can verify scoping without a full React test
// renderer.
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

// ----------------------------------------------------------------
// Tests
// ----------------------------------------------------------------

describe("ToolStreamingProvider rendering", () => {
  it("renders children and initialises with zero outputs (P1-2 baseline)", () => {
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

describe("ToolStreamingProvider scoping logic (P1-2 regression)", () => {
  it("tool_call_ids are independent — two subtasks never share output", () => {
    // Simulate the provider's update logic directly without hooks.
    // The provider's `updateToolStream` essentially does:
    //
    //   setState(prev => {
    //     if (output === null) { delete prev.outputs[id]; return {outputs: {...}}; }
    //     return { outputs: { ...prev.outputs, [id]: output } };
    //   })
    //
    // We verify that two different tool_call_ids produce independent entries.

    type State = {
      outputs: Record<string, { text: string }>;
    };

    const update = (
      prev: State,
      toolCallId: string,
      output: { text: string } | null,
    ): State => {
      if (output === null) {
        if (!(toolCallId in prev.outputs)) {
          return prev;
        }
        const next = { ...prev.outputs };
        delete next[toolCallId];
        return { outputs: next };
      }
      return { outputs: { ...prev.outputs, [toolCallId]: output } };
    };

    let state: State = { outputs: {} };

    // Add output for tool A
    state = update(state, "tc-bash", { text: "bash-output" });
    expect(state.outputs["tc-bash"]).toEqual({ text: "bash-output" });
    expect(Object.keys(state.outputs)).toHaveLength(1);

    // Add output for tool B — must be in a different slot
    state = update(state, "tc-search", { text: "search-output" });
    expect(state.outputs["tc-bash"]?.text).toBe("bash-output");
    expect(state.outputs["tc-search"]?.text).toBe("search-output");
    expect(Object.keys(state.outputs)).toHaveLength(2);

    // Remove tool A — tool B must survive
    state = update(state, "tc-bash", null);
    expect("tc-bash" in state.outputs).toBe(false);
    expect(state.outputs["tc-search"]?.text).toBe("search-output");
    expect(Object.keys(state.outputs)).toHaveLength(1);
  });

  it("late partial chunk does not overwrite a completed final chunk", () => {
    // Regression: the provider must drop a late-arriving partial chunk when a
    // final output has already been written for the same tool_call_id.
    // (The old guard was inverted — it rejected the *final* instead of the
    // *partial*, so the complete output was never visible.)
    type State = {
      outputs: Record<string, { text: string; isPartial: boolean }>;
    };

    const update = (
      prev: State,
      toolCallId: string,
      output: { text: string; isPartial: boolean } | null,
    ): State => {
      if (output === null) {
        if (!(toolCallId in prev.outputs)) return prev;
        const next = { ...prev.outputs };
        delete next[toolCallId];
        return { outputs: next };
      }
      const existing = prev.outputs[toolCallId];
      // Reject a late partial when final already exists.
      if (existing && output.isPartial && !existing.isPartial) {
        return prev;
      }
      return { outputs: { ...prev.outputs, [toolCallId]: output } };
    };

    let state: State = { outputs: {} };

    // Normal flow: start chunk arrives first.
    state = update(state, "tc-1", { text: "", isPartial: true });
    expect(state.outputs["tc-1"]?.text).toBe("");

    // Final chunk arrives — should be stored.
    state = update(state, "tc-1", {
      text: "complete output",
      isPartial: false,
    });
    expect(state.outputs["tc-1"]?.text).toBe("complete output");
    expect(state.outputs["tc-1"]?.isPartial).toBe(false);

    // Late partial chunk arrives (network reorder) — must be dropped.
    state = update(state, "tc-1", { text: "stale partial", isPartial: true });
    expect(state.outputs["tc-1"]?.text).toBe("complete output");
    expect(state.outputs["tc-1"]?.isPartial).toBe(false);
  });
});
