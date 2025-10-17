import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { normalizeMathForEditor, normalizeMathForDisplay } from "../src/core/utils/markdown.ts";

describe("markdown math normalization for editor", () => {
  it("converts LaTeX display delimiters to $$ for editor", () => {
    const input = "Here is a formula \\[E=mc^2\\] in the text.";
    const output = normalizeMathForEditor(input);
    assert.strictEqual(output, "Here is a formula $$E=mc^2$$ in the text.");
  });

  it("converts LaTeX display delimiters to $ with \\ for editor", () => {
    const input = "Here is a formula \\(F = k\\frac{q_1q_2}{r^2}\\) in the text.";
    const output = normalizeMathForEditor(input);
    assert.strictEqual(output, "Here is a formula $F = k\\frac{q_1q_2}{r^2}$ in the text.");
  });

  it("converts LaTeX display delimiters to $ with \\\\ for editor", () => {
    const input = "Here is a formula \\(F = k\\\\frac{q_1q_2}{r^2}\\) in the text.";
    const output = normalizeMathForEditor(input);
    assert.strictEqual(output, "Here is a formula $F = k\\frac{q_1q_2}{r^2}$ in the text.");
  });

  it("converts escaped LaTeX display delimiters to $$ for editor", () => {
    const input = "Formula \\\\[x^2 + y^2 = z^2\\\\] here.";
    const output = normalizeMathForEditor(input);
    assert.strictEqual(output, "Formula $$x^2 + y^2 = z^2$$ here.");
  });

  it("converts LaTeX inline delimiters to $ for editor", () => {
    const input = "Inline formula \\(a + b = c\\) in text.";
    const output = normalizeMathForEditor(input);
    assert.strictEqual(output, "Inline formula $a + b = c$ in text.");
  });

  it("converts escaped LaTeX inline delimiters to $ for editor", () => {
    const input = "Inline \\\\(x = 5\\\\) here.";
    const output = normalizeMathForEditor(input);
    assert.strictEqual(output, "Inline $x = 5$ here.");
  });

  it("handles mixed delimiters for editor", () => {
    const input = "Display \\[E=mc^2\\] and inline \\(F=ma\\) formulas.";
    const output = normalizeMathForEditor(input);
    assert.strictEqual(output, "Display $$E=mc^2$$ and inline $F=ma$ formulas.");
  });

  it("preserves already normalized math syntax for editor", () => {
    const input = "Already normalized $$E=mc^2$$ and $F=ma$ formulas.";
    const output = normalizeMathForEditor(input);
    assert.strictEqual(output, "Already normalized $$E=mc^2$$ and $F=ma$ formulas.");
  });
});

describe("markdown math normalization for display", () => {
  it("converts LaTeX display delimiters to $$ for display", () => {
    const input = "Here is a formula \\[E=mc^2\\] in the text.";
    const output = normalizeMathForDisplay(input);
    assert.strictEqual(output, "Here is a formula $$E=mc^2$$ in the text.");
  });

  it("converts escaped LaTeX display delimiters to $$ for display", () => {
    const input = "Formula \\\\[x^2 + y^2 = z^2\\\\] here.";
    const output = normalizeMathForDisplay(input);
    assert.strictEqual(output, "Formula $$x^2 + y^2 = z^2$$ here.");
  });

  it("converts LaTeX inline delimiters to $$ for display", () => {
    const input = "Inline formula \\(a + b = c\\) in text.";
    const output = normalizeMathForDisplay(input);
    assert.strictEqual(output, "Inline formula $$a + b = c$$ in text.");
  });

  it("converts escaped LaTeX inline delimiters to $$ for display", () => {
    const input = "Inline \\\\(x = 5\\\\) here.";
    const output = normalizeMathForDisplay(input);
    assert.strictEqual(output, "Inline $$x = 5$$ here.");
  });

  it("handles mixed delimiters for display", () => {
    const input = "Display \\[E=mc^2\\] and inline \\(F=ma\\) formulas.";
    const output = normalizeMathForDisplay(input);
    assert.strictEqual(output, "Display $$E=mc^2$$ and inline $$F=ma$$ formulas.");
  });

  it("handles complex physics formulas", () => {
    const input = "Maxwell equation: \\[\\nabla \\times \\vec{E} = -\\frac{\\partial \\vec{B}}{\\partial t}\\]";
    const output = normalizeMathForDisplay(input);
    assert.ok(output.includes("$$"));
    assert.ok(output.includes("nabla"));
  });
});

describe("markdown math round-trip consistency", () => {
  it("handles editor normalization consistently", () => {
    const original = "Formula \\[E=mc^2\\] and \\(F=ma\\)";
    const forEditor = normalizeMathForEditor(original);
    
    // Simulate editor output (should have $ and $$)
    assert.ok(forEditor.includes("$$"));
    assert.ok(forEditor.includes("$"));
  });

  it("handles multiple formulas correctly", () => {
    const input = `
# Physics Formulas

Energy: \\[E = mc^2\\]

Force: \\(F = ma\\)

Momentum: \\[p = mv\\]
    `;
    
    const forEditor = normalizeMathForEditor(input);
    const forDisplay = normalizeMathForDisplay(input);
    
    // Both should have converted the delimiters
    assert.ok(forEditor.includes("$$"));
    assert.ok(forDisplay.includes("$$"));
  });

  it("preserves text content around formulas", () => {
    const input = "Text before \\[E=mc^2\\] text after";
    const output = normalizeMathForEditor(input);
    
    assert.ok(output.startsWith("Text before"));
    assert.ok(output.endsWith("text after"));
  });
});
