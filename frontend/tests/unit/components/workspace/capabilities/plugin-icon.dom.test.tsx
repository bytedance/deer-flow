import { afterEach, expect, it } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";

import { PluginIcon } from "@/components/workspace/capabilities/plugin-icon";

afterEach(cleanup);

it("does not infer a provider from a custom server name", () => {
  for (const name of ["github", "notion", "feishu", "brave", "postgres"]) {
    const { container, unmount } = render(<PluginIcon name={name} />);
    expect(container.querySelector("img")).toBeNull();
    unmount();
  }
});

it("uses explicit catalog assets and rejects remote assets", () => {
  const { container, rerender } = render(
    <PluginIcon name="team-code" asset="/images/plugins/github.svg" />,
  );
  expect(container.querySelector("img")?.getAttribute("src")).toBe(
    "/images/plugins/github.svg",
  );
  rerender(
    <PluginIcon name="github" asset="https://external.example/icon.png" />,
  );
  expect(container.querySelector("img")).toBeNull();
});
