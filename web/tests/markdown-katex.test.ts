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
    expect(() => {
      render("\\curl{\\vect{B}} = \\mu_0 \\vect{J} + \\mu_0 \\varepsilon_0 \\pdv{\\vect{E}}{t}");
    }).not.toThrow();
  });

  it("renders quantum mechanics bra-ket notation", () => {
    const html = render("\\braket{\\psi}{\\phi}");
    expect(html.includes("⟨") && html.includes("⟩")).toBeTruthy();
  });

  it("renders vector magnitude formula with subscripts and square root", () => {
    const html = render("(F_1) (F_2), (F=\\sqrt{F_1^2+F_2^2})");
    expect(html.includes("F")).toBeTruthy();
    expect(html.includes("₁") || html.includes("sub")).toBeTruthy(); // subscript check
    expect(html.includes("√") || html.includes("sqrt")).toBeTruthy(); // square root check
  });

  it("renders chemical equations via mhchem", () => {
    expect(() => {
      render("\\ce{H2O ->[\\Delta] H+ + OH-}");
    }).not.toThrow();
  });
});
