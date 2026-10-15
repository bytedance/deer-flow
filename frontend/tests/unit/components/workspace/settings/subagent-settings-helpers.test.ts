import { describe, expect, it } from "@rstest/core";

import {
  isValidManagedSubagentName,
  optionalNameListFromDraft,
  optionalNameListToDraft,
  positiveInteger,
} from "@/components/workspace/settings/subagent-settings-helpers";

describe("managed Subagent optional name lists", () => {
  it("round-trips inherit-all, deny-all, and selected as distinct states", () => {
    expect(optionalNameListToDraft(null)).toEqual({ mode: "all", text: "" });
    expect(optionalNameListToDraft([])).toEqual({ mode: "none", text: "" });
    expect(optionalNameListToDraft(["read_file", "web_search"])).toEqual({
      mode: "selected",
      text: "read_file, web_search",
    });

    expect(optionalNameListFromDraft("all", "ignored")).toBeNull();
    expect(optionalNameListFromDraft("none", "ignored")).toEqual([]);
    expect(
      optionalNameListFromDraft(
        "selected",
        " read_file, web_search, read_file ",
      ),
    ).toEqual(["read_file", "web_search"]);
  });

  it("keeps an empty selected list as [] instead of widening it to null", () => {
    expect(optionalNameListFromDraft("selected", "  ")).toEqual([]);
  });
});

describe("managed Subagent field validation", () => {
  it("matches the backend name and positive-integer boundaries", () => {
    expect(isValidManagedSubagentName("creative-planner")).toBe(true);
    expect(isValidManagedSubagentName("../planner")).toBe(false);
    expect(isValidManagedSubagentName("creative_planner")).toBe(false);
    expect(positiveInteger("1")).toBe(1);
    expect(positiveInteger("1.5")).toBeNull();
    expect(positiveInteger("")).toBeNull();
  });
});
