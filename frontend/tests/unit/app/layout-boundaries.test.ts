import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

const FRONTEND_ROOT = path.resolve(__dirname, "../../..");

function source(relativePath: string) {
  return readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");
}

describe("layout performance boundaries", () => {
  it("keeps request locale and rich-content styles out of the root layout", () => {
    const rootLayout = source("src/app/layout.tsx");

    expect(rootLayout).not.toContain("detectLocaleServer");
    expect(rootLayout).not.toContain("I18nProvider");
    expect(rootLayout).not.toContain("katex/dist/katex.min.css");
    expect(rootLayout).not.toContain("streamdown/styles.css");
    expect(rootLayout).toContain("DEFAULT_LOCALE");
  });

  it("assigns rich-content styles to routes that render them", () => {
    expect(source("src/app/workspace/layout.tsx")).toContain(
      'import "streamdown/styles.css"',
    );
    expect(source("src/app/[lang]/docs/layout.tsx")).toContain(
      'import "katex/dist/katex.min.css"',
    );
    expect(source("src/app/blog/layout.tsx")).toContain(
      'import "katex/dist/katex.min.css"',
    );
  });

  it("passes only serializable locale state through server layouts", () => {
    for (const layout of [
      source("src/app/(auth)/layout.tsx"),
      source("src/app/workspace/layout.tsx"),
    ]) {
      expect(layout).toContain("detectLocaleServer");
      expect(layout).not.toContain("initialTranslations");
      expect(layout).not.toContain("getI18n");
    }
  });
});
