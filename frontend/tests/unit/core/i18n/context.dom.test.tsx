import { describe, expect, it } from "@rstest/core";
import { fireEvent, render, screen } from "@testing-library/react";

import { I18nProvider, useI18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

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
  it("keeps locale and its dynamically loaded dictionary in sync", async () => {
    render(
      <I18nProvider initialLocale="en-US" initialTranslations={enUS}>
        <Consumer />
      </I18nProvider>,
    );

    expect(screen.getByText("en-US:English")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "switch" }));

    expect(await screen.findByText("zh-CN:中文")).toBeTruthy();
    expect(document.documentElement.lang).toBe("zh-CN");
  });
});
