import { afterEach, expect, it, rs } from "@rstest/core";

import { safeLocalStorage } from "@/core/settings/local";
import {
  getBaseSettingsSnapshot,
  getThreadModelSnapshot,
  selectThreadModel,
  updateLocalSettings,
} from "@/core/settings/store";

afterEach(() => {
  rs.restoreAllMocks();
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
