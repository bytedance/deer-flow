import { expect, test } from "@rstest/core";

import {
  hasRenderedThreadStateUpdate,
  reduceThreadStateUpdates,
} from "@/core/threads/stream-state";
import type { AgentThreadState, ArtifactEntry } from "@/core/threads/types";

function entry(handle: string): ArtifactEntry {
  return {
    handle,
    tool_name: "make_report",
    tool_call_id: `call_${handle}`,
    call_index: 0,
    artifact_type: "file",
    display_name: `${handle}.csv`,
    real_ref: `/mnt/user-data/outputs/${handle}.csv`,
    consumed_by: [],
  };
}

test("folds artifact capture, consumption and retention without values frames", () => {
  const first = entry("art_11111111");
  const second = entry("art_22222222");
  const third = entry("art_33333333");
  const previous: AgentThreadState = {
    title: "Reports",
    messages: [],
    tool_artifacts: [first],
  };
  const consumed = { ...first, consumed_by: ["call_read"] };
  const data = {
    "ArtifactCaptureMiddleware.before_model": {
      tool_artifacts: [second, consumed],
    },
    next_capture: {
      tool_artifacts: [third, { op: "trim_to", keep: 2 }],
    },
  };
  expect(hasRenderedThreadStateUpdate(data)).toBe(true);
  expect(reduceThreadStateUpdates(previous, data)).toEqual({
    tool_artifacts: [second, third],
  });
  expect(previous.tool_artifacts).toEqual([first]);
  expect(
    reduceThreadStateUpdates(previous, {
      capture: { tool_artifacts: [second, consumed] },
    }),
  ).toEqual({ tool_artifacts: [consumed, second] });
});

test("preserves the registry on empty updates and enforces its absolute ceiling", () => {
  const first = entry("art_11111111");
  const previous: AgentThreadState = {
    title: "Reports",
    messages: [],
    tool_artifacts: [first],
  };
  expect(
    reduceThreadStateUpdates(previous, {
      capture: { tool_artifacts: [] },
    }),
  ).toEqual({ tool_artifacts: [first] });
  const many = Array.from({ length: 1001 }, (_, i) =>
    entry(`art_${i.toString(16).padStart(8, "0")}`),
  );
  expect(
    reduceThreadStateUpdates(previous, {
      capture: { tool_artifacts: many },
    })?.tool_artifacts,
  ).toEqual(many.slice(-1000));
});
