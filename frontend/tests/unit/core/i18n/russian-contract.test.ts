import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "@rstest/core";
import { SUPPORTED_LOCALES } from "@/core/i18n/locale";

describe("Russian UI locale contract", () => {
  it("is shared with the runtime and memory", () => {
    const contract = JSON.parse(
      readFileSync(
        resolve(__dirname, "../../../../../contracts/ui_locales.v1.json"),
        "utf-8",
      ),
    ) as { languages: Record<string, string> };
    expect([...SUPPORTED_LOCALES].sort()).toEqual(
      Object.keys(contract.languages).sort(),
    );
    expect(contract.languages["ru-RU"]).toBe("Russian");
  });
});
