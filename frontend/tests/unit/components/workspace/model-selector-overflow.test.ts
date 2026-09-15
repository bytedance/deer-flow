import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");
const SELECTED_MODEL_WRAPPER_PATTERN =
  /<ModelPickerTrigger asChild>[\s\S]*?<div className="([^"]*)">\s*<ModelSelectorName/;

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

describe("model picker integration", () => {
  it.each([
    {
      relativePath: "src/components/workspace/input-box.tsx",
      open: "modelDialogOpen",
      selectedModelName: "selectedModel?.name",
      onModelSelect: "handleModelSelect",
    },
    {
      relativePath: "src/components/workspace/sidecar/sidecar-panel.tsx",
      open: "open",
      selectedModelName: "selectedModel.name",
      onModelSelect: "onModelSelect",
    },
  ])(
    "uses ModelPickerContent inside the anchored picker in $relativePath",
    ({ relativePath, open, selectedModelName, onModelSelect }) => {
      const contents = source(relativePath);
      const picker = /<ModelPickerContent[\s\S]*?\/>/.exec(contents)?.[0];

      expect(contents).toMatch(/<ModelPicker\s/);
      expect(contents).toContain("<ModelPickerTrigger asChild>");
      expect(picker).toBeDefined();
      expect(picker).toMatch(
        new RegExp(`open=\\{${open.replace("?", "\\?")}\\}`),
      );
      expect(picker).toMatch(/models=\{models\}/);
      expect(picker).toMatch(
        new RegExp(
          `selectedModelName=\\{${selectedModelName.replace("?", "\\?")}\\}`,
        ),
      );
      expect(picker).toMatch(
        new RegExp(`onModelSelect=\\{${onModelSelect}\\}`),
      );
      for (const legacyComponent of [
        "ModelSelectorContent",
        "ModelSelectorInput",
        "ModelSelectorList",
        "ModelSelectorItem",
      ]) {
        expect(contents).not.toContain(`<${legacyComponent}`);
      }
    },
  );
});
