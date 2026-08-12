import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { CopyButton } from "@/components/workspace/copy-button";
import { I18nProvider } from "@/core/i18n/context";

afterEach(cleanup);

function renderCopyButton(props?: { "aria-label"?: string }) {
  return render(
    <I18nProvider initialLocale="en-US">
      <CopyButton clipboardData="copied text" {...props} />
    </I18nProvider>,
  );
}

describe("CopyButton", () => {
  it("names the icon-only trigger without relying on the tooltip", () => {
    renderCopyButton();

    // A Radix tooltip only contributes `aria-describedby`, which is a
    // description rather than an accessible name, so the button would
    // otherwise be announced as an unlabelled "button".
    const button = screen.getByRole("button", { name: "Copy to clipboard" });
    expect(button.getAttribute("aria-label")).toBe("Copy to clipboard");
  });

  it("lets a caller override the label with a more specific one", () => {
    renderCopyButton({ "aria-label": "Copy citation" });

    expect(screen.getByRole("button", { name: "Copy citation" })).toBeTruthy();
  });
});
