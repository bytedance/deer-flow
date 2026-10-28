import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "@rstest/core";

import { SUPPORTED_LOCALES } from "@/core/i18n/locale";

describe("UI locale contract", () => {
  it("supports the same locales as the Gateway and DeerMem", () => {
    const contract = JSON.parse(
      readFileSync(
        resolve(__dirname, "../../../../../contracts/ui_locales.v1.json"),
        "utf-8",
      ),
    ) as { languages: Record<string, string> };

    expect([...SUPPORTED_LOCALES].sort()).toEqual(
      Object.keys(contract.languages).sort(),
    );
  });
});
