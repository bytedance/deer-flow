import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { I18nProvider, useI18nContext } from "@/core/i18n/context";

afterEach(cleanup);

function Consumer() {
  const { locale, setLocale, t } = useI18nContext();
  return (
    <>
      <output>{`${locale}:${t.locale.localName}`}</output>
      <button type="button" onClick={() => setLocale("zh-CN")}>
        switch
      </button>
    </>
  );
}

describe("I18nProvider", () => {
  it("keeps locale and its dictionary in sync", async () => {
    render(
      <I18nProvider initialLocale="en-US">
        <Consumer />
      </I18nProvider>,
    );

    expect(screen.getByText("en-US:English")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "switch" }));

    expect(await screen.findByText("zh-CN:中文")).toBeTruthy();
    expect(document.documentElement.lang).toBe("zh-CN");
  });

  it("selects the initial dictionary inside the client boundary", () => {
    render(
      <I18nProvider initialLocale="zh-CN">
        <Consumer />
      </I18nProvider>,
    );

    expect(screen.getByText("zh-CN:中文")).toBeTruthy();
  });
});
