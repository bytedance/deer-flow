import { afterEach, expect, it, rs } from "@rstest/core";

import { safeLocalStorage } from "@/core/settings/local";
import {
  getBaseSettingsSnapshot,
  getThreadModelSnapshot,
  selectThreadModel,
  updateLocalSettings,
  updateThreadSettings,
} from "@/core/settings/store";
import { buildRunContext } from "@/core/threads/hooks";

afterEach(() => {
  rs.restoreAllMocks();
});

it("submits each chat's own effort after another chat edits the account preference", () => {
  const submit = (threadId: string) =>
    buildRunContext({ threadId, settings: getBaseSettingsSnapshot().context });
  updateThreadSettings("chat-a", "context", { reasoning_effort: "high" });
  updateThreadSettings("chat-b", "context", { reasoning_effort: "medium" });
  expect(submit("chat-a")).toMatchObject({
    reasoning_effort: "high",
    mode_default_fields: ["thinking_enabled"],
  });
  expect(submit("chat-b")).toMatchObject({
    reasoning_effort: "medium",
    mode_default_fields: ["thinking_enabled"],
  });
  expect(submit("fresh-chat").mode_default_fields).toContain(
    "reasoning_effort",
  );
  updateThreadSettings("chat-a", "context", {
    mode: "ultra",
    reasoning_effort: "high",
  });
  expect(submit("chat-a").mode_default_fields).toContain("reasoning_effort");
  expect(submit("chat-b").reasoning_effort).toBe("medium");
});

it("does not claim to save a default when browser storage rejects the write", () => {
  rs.spyOn(safeLocalStorage, "setItem").mockReturnValue(false);
  expect(() => selectThreadModel("blocked-write-thread", "model-B")).toThrow();
  expect(getThreadModelSnapshot("blocked-write-thread")).toBeUndefined();
});

it("persists only the selected conversation without editing account preferences", () => {
  updateLocalSettings("context", { model_name: "parent-A" });
  const before = getBaseSettingsSnapshot();
  selectThreadModel("selection-test-thread", "model-B");
  expect(getThreadModelSnapshot("selection-test-thread")).toBe("model-B");
  expect(getBaseSettingsSnapshot()).toBe(before);
  expect(getThreadModelSnapshot("unrelated-test-thread")).toBeUndefined();
  expect(
    localStorage.getItem("deerflow.thread-model.selection-test-thread"),
  ).toBe("model-B");
});
