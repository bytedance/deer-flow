import { describe, expect, it } from "vitest";

import { A2UI_DEBUG_DEFAULT_PROPS } from "@/components/debug/a2ui-default-props";
import { KNOWN_COMPONENTS } from "@/core/genui";
import { sanitizeProps } from "@/core/genui/sanitizer";
import { validateProps } from "@/core/genui/validator";

describe("A2UI debug default props", () => {
  it("defines defaults for every known component", () => {
    expect(Object.keys(A2UI_DEBUG_DEFAULT_PROPS).sort()).toEqual(
      [...KNOWN_COMPONENTS].sort(),
    );
  });

  it("uses validator-compatible example props", () => {
    for (const component of KNOWN_COMPONENTS) {
      const raw = A2UI_DEBUG_DEFAULT_PROPS[component];
      expect(raw, `missing default props for ${component}`).toBeTruthy();

      const parsed = JSON.parse(raw!);
      const sanitized = sanitizeProps(component, parsed);
      const result = validateProps(component, sanitized);

      expect(
        result.success,
        `${component} default props should validate: ${result.error ?? "unknown error"}`,
      ).toBe(true);
    }
  });
});
