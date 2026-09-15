import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");
const SELECTED_MODEL_WRAPPER_PATTERN =
  /<ModelSelectorTrigger asChild>[\s\S]*?<div className="([^"]*)">\s*<ModelSelectorName/;

function source(relativePath: string) {
  return readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");
}

function selectedModelWrapperClasses(relativePath: string) {
  return SELECTED_MODEL_WRAPPER_PATTERN.exec(source(relativePath))?.[1]?.split(
    /\s+/,
  );
}

describe("selected model name truncation", () => {
  it.each([
    "src/components/workspace/input-box.tsx",
    "src/components/workspace/sidecar/sidecar-panel.tsx",
  ])("lets ModelSelectorName stretch in %s", (relativePath) => {
    const classes = selectedModelWrapperClasses(relativePath);

    expect(classes).toEqual(
      expect.arrayContaining(["flex", "min-w-0", "flex-col"]),
    );
    expect(classes).not.toContain("items-start");
  });
});
