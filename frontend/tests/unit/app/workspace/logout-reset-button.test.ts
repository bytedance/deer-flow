import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import { LogoutResetButton } from "@/app/workspace/logout-reset-button";

test("renders logout reset as a button instead of a GET link", () => {
  const html = renderToStaticMarkup(createElement(LogoutResetButton));

  expect(html).toContain("Logout &amp; Reset");
  expect(html).toContain('type="button"');
  expect(html).not.toContain('href="/api/v1/auth/logout"');
});
