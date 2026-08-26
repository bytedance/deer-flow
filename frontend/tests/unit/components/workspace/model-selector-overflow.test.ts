import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");
const SELECTED_MODEL_TRIGGER_PATTERN =
  /<ModelSelectorTrigger asChild>[\s\S]*?<\/ModelSelectorTrigger>/;

function source(relativePath: string) {
  return readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");
}

function selectedModelTrigger(relativePath: string) {
  return SELECTED_MODEL_TRIGGER_PATTERN.exec(source(relativePath))?.[0];
}

describe("selected model name truncation", () => {
  it.each([
    "src/components/workspace/input-box.tsx",
    "src/components/workspace/sidecar/sidecar-panel.tsx",
  ])("lets ModelSelectorName stretch in %s", (relativePath) => {
    const trigger = selectedModelTrigger(relativePath);

    expect(trigger).toContain("<ModelSelectorName");
    expect(trigger).not.toContain("items-start");
  });
});
