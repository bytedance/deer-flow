import { describe, it } from "node:test";
import assert from "node:assert/strict";

import katex from "katex";

import { katexOptions } from "../src/core/markdown/katex";

function render(expression: string) {
  return katex.renderToString(expression, {
    ...katexOptions,
    displayMode: true,
  });
}

describe("markdown physics katex support", () => {
  it("renders vector calculus operators", () => {
    assert.doesNotThrow(() => {
      render("\\curl{\\vect{B}} = \\mu_0 \\vect{J} + \\mu_0 \\varepsilon_0 \\pdv{\\vect{E}}{t}");
    });
  });

  it("renders quantum mechanics bra-ket notation", () => {
    const html = render("\\braket{\\psi}{\\phi}");
    assert.ok(html.includes("⟨") && html.includes("⟩"));
  });

  it("renders vector magnitude formula with subscripts and square root", () => {
  const html = render("(F_1) (F_2), (F=\\sqrt{F_1^2+F_2^2})");
  assert.ok(html.includes("F"));
  assert.ok(html.includes("₁") || html.includes("sub")); // subscript check
  assert.ok(html.includes("√") || html.includes("sqrt")); // square root check
  });

  it("renders chemical equations via mhchem", () => {
    assert.doesNotThrow(() => {
      render("\\ce{H2O ->[\\Delta] H+ + OH-}");
    });
  });
});
