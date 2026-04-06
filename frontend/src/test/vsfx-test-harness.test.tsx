import { expect, test } from "vitest";

import { render, screen } from "@/test/render";

function HarnessSmokeTest() {
  return (
    <main>
      <h1>VSFX harness smoke test</h1>
      <p>Shared render helper is available.</p>
    </main>
  );
}

test("renders a simple React node through the shared harness helper", () => {
  render(<HarnessSmokeTest />);

  expect(
    screen.getByRole("heading", { name: "VSFX harness smoke test" }),
  ).toBeInTheDocument();
});

test("reports a missing element with a DOM-based assertion", () => {
  render(<HarnessSmokeTest />);

  expect(() => {
    expect(
      screen.getByRole("heading", { name: "Missing VSFX heading" }),
    ).toBeInTheDocument();
  }).toThrowError(/Unable to find an accessible element with the role "heading"/i);
});
