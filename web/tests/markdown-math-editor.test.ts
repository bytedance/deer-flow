import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { normalizeMathForEditor, normalizeMathForDisplay, unescapeLatexInMath } from "../src/core/utils/markdown.ts";

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

describe("markdown math unescape (issue #608 fix)", () => {
  it("unescapes asterisks in inline math", () => {
    const escaped = "Formula $(f \\* g)(t) = t^2$";
    const unescaped = unescapeLatexInMath(escaped);
    assert.strictEqual(unescaped, "Formula $(f * g)(t) = t^2$");
  });

  it("unescapes underscores in display math", () => {
    const escaped = "Formula $$x\\_{n+1} = x_n - f(x_n)/f'(x_n)$$";
    const unescaped = unescapeLatexInMath(escaped);
    assert.strictEqual(unescaped, "Formula $$x_{n+1} = x_n - f(x_n)/f'(x_n)$$");
  });

  it("unescapes backslashes for LaTeX commands", () => {
    const escaped = "Formula $$\\\\int_{-\\\\infty}^{\\\\infty} f(x)dx$$";
    const unescaped = unescapeLatexInMath(escaped);
    assert.strictEqual(unescaped, "Formula $$\\int_{-\\infty}^{\\infty} f(x)dx$$");
  });

  it("unescapes square brackets in math", () => {
    const escaped = "Array $a\\[0\\] = b$ and $$c\\[n\\] = d$$";
    const unescaped = unescapeLatexInMath(escaped);
    assert.strictEqual(unescaped, "Array $a[0] = b$ and $$c[n] = d$$");
  });

  it("handles complex formula from issue #608", () => {
    const escaped = `| Discrete | $(f \\* g)\\[n\\] = \\\\sum\\_{k=-\\\\infty}^{\\\\infty} f\\[k\\]g\\[n-k\\]$ |`;
    const unescaped = unescapeLatexInMath(escaped);
    // Should unescape special characters within math delimiters
    assert.ok(unescaped.includes("(f * g)"));
    assert.ok(unescaped.includes("[n]"));
    assert.ok(unescaped.includes("\\sum"));
    assert.ok(unescaped.includes("_{k"));
  });

  it("preserves text outside math delimiters", () => {
    const escaped = "Before $a \\* b$ middle $$c \\* d$$ after";
    const unescaped = unescapeLatexInMath(escaped);
    assert.ok(unescaped.startsWith("Before"));
    assert.ok(unescaped.endsWith("after"));
    assert.ok(unescaped.includes("middle"));
  });

  it("handles mixed escaped and unescaped characters", () => {
    const escaped = "$$f(x) = \\\\int_0^\\\\infty e^{-x^2} \\* dx$$";
    const unescaped = unescapeLatexInMath(escaped);
    assert.strictEqual(unescaped, "$$f(x) = \\int_0^\\infty e^{-x^2} * dx$$");
  });

  it("handles multiple inline formulas", () => {
    const escaped = "Formulas $a \\* b$ and $c \\* d$ and $e \\* f$";
    const unescaped = unescapeLatexInMath(escaped);
    const matches = unescaped.match(/\* /g);
    assert.strictEqual(matches?.length, 3);
  });

  it("does not modify non-formula text with backslashes", () => {
    const text = "Use \\* in text and $a \\* b$ in formula";
    const unescaped = unescapeLatexInMath(text);
    // Text outside formulas should not be changed
    assert.ok(unescaped.includes("Use \\*"));
    assert.ok(unescaped.includes("a * b"));
  });

  it("handles edge case of empty math delimiters", () => {
    const escaped = "Empty $$ and $$$$";
    const unescaped = unescapeLatexInMath(escaped);
    // Should not crash, just return as-is
    assert.ok(typeof unescaped === "string");
  });

  it("round-trip test: escaped content → unescape → original", () => {
    // This represents what tiptap-markdown returns after editing
    // Specific characters are escaped: * → \*, _ → \_, [ → \[, ] → \]
    const escapedByTiptap = "Physics: $(f \\* g)\\[n\\] = \\sum_{k=-\\infty}^{\\infty} f\\[k\\]g\\[n\\-k\\]$";
    
    // Apply unescape
    const unescaped = unescapeLatexInMath(escapedByTiptap);
    
    // Should restore formula content and preserve backslash sequences
    assert.ok(unescaped.includes("(f * g)"));
    assert.ok(unescaped.includes("[n]"));
    assert.ok(unescaped.includes("\\sum"));
    assert.ok(unescaped.includes("f[k]"));
  });
});
