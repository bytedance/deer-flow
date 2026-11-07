import { describe, expect, it } from "@rstest/core";

import { filterModels, projectRecentModels } from "@/core/models/catalog";
import type { Model } from "@/core/models/types";

const models: Model[] = [
  {
    id: "a",
    name: "a",
    model: "api-a",
    display_name: "快速模型",
    provider: "First",
  },
  {
    id: "b",
    name: "b",
    model: "api-b",
    display_name: "Second",
    provider: "Other",
  },
];
describe("model catalog selection", () => {
  it("searches names, IDs and providers literally, intersecting the provider filter", () => {
    expect(filterModels(models, " 快速 ")).toEqual([models[0]]);
    expect(filterModels(models, "API-A")).toEqual([models[0]]);
    expect(filterModels(models, "First", "Other")).toEqual([]);
    expect(filterModels(models, ".*")).toEqual([]);
  });
  it("orders recent authorized models without duplicating favorites or deleted models", () => {
    expect(
      projectRecentModels(models, ["b", "removed", "a", "b"], ["a"]),
    ).toEqual([models[1]]);
  });
});
