import { afterEach, expect, test } from "@rstest/core";
import { cleanup, render } from "@testing-library/react";

import { ChannelProviderIcon } from "@/components/workspace/channels/channel-provider-icon";

afterEach(cleanup);

test("renders QQ with caller-provided accessible label and styling", () => {
  const { getByRole } = render(
    <ChannelProviderIcon
      provider="QQ"
      role="img"
      aria-label="QQ"
      aria-hidden={false}
      className="size-8"
    />,
  );
  expect(getByRole("img", { name: "QQ" }).getAttribute("class")).toContain(
    "size-8",
  );
});

test("renders collision-safe official Buzz marks", () => {
  const { container } = render(
    <>
      <ChannelProviderIcon provider="buzz" />
      <ChannelProviderIcon provider="BUZZ" />
    </>,
  );

  const icons = Array.from(container.querySelectorAll("svg"));
  expect(icons).toHaveLength(2);
  expect(icons.map((icon) => icon.getAttribute("viewBox"))).toEqual([
    "0 0 466 309",
    "0 0 466 309",
  ]);
  expect(icons.map((icon) => icon.getAttribute("fill"))).toEqual([
    "currentColor",
    "currentColor",
  ]);

  const maskIds = Array.from(container.querySelectorAll("mask"), (mask) =>
    mask.getAttribute("id"),
  );
  expect(maskIds).toHaveLength(2);
  expect(new Set(maskIds).size).toBe(2);
});
