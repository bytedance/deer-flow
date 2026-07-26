import { describe, expect, test } from "@rstest/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { RememberSessionOption } from "@/components/auth/remember-session-option";
import { I18nContext } from "@/core/i18n/context";

describe("RememberSessionOption", () => {
  test("uses the active locale for setup and login copy", () => {
    const markup = renderToStaticMarkup(
      createElement(
        I18nContext.Provider,
        {
          value: {
            locale: "zh-CN",
            setLocale: () => undefined,
          },
        },
        createElement(RememberSessionOption, {
          checked: true,
          onCheckedChange: () => undefined,
        }),
      ),
    );

    expect(markup).toContain("保持登录");
    expect(markup).toContain(
      "下次打开 DeerFlow 时尽量保持当前会话，仅保存邮箱，不保存密码。",
    );
    expect(markup).not.toContain("Keep me signed in");
  });
});
