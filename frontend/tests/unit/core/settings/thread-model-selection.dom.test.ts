import { afterEach, expect, it, rs } from "@rstest/core";

import { safeLocalStorage } from "@/core/settings/local";
import {
  getBaseSettingsSnapshot,
  getThreadModelSnapshot,
  reconcileThreadEffort,
  resolveThreadContext,
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

it("drops an unsupported effort even when another chat has already resolved the fallback model", () => {
  updateLocalSettings("context", { model_name: "extended" });
  updateThreadSettings("old-chat", "context", { reasoning_effort: "max" });
  updateThreadSettings("other-chat", "context", { reasoning_effort: "medium" });
  resolveThreadContext("other-chat", {
    model_name: "legacy",
    reasoning_effort: "medium",
  });
  const settings = getBaseSettingsSnapshot().context;
  reconcileThreadEffort("old-chat", settings.model_name, {
    name: "legacy",
    model: "legacy",
    id: "legacy",
    display_name: "Legacy",
    supports_reasoning_effort: true,
  });
  expect(buildRunContext({ threadId: "old-chat", settings })).toMatchObject({
    model_name: "legacy",
    reasoning_effort: "medium",
    mode_default_fields: ["thinking_enabled", "reasoning_effort"],
  });
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
