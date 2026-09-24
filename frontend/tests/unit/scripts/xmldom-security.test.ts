import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "@rstest/core";

test("the lockfile excludes xmldom versions affected by GHSA-965w-775f-mr7g", () => {
  const lockfile = readFileSync(
    resolve(process.cwd(), "pnpm-lock.yaml"),
    "utf8",
  );
  const versions = Array.from(
    lockfile.matchAll(/^  '@xmldom\/xmldom@([^']+)':/gm),
    (match) => match[1]!,
  );

  // The dependency can disappear entirely if Nextra drops its XML parser.
  for (const version of versions) {
    expect(version).not.toMatch(/^0\.9\.(?:[0-9]|10|11)(?:$|[(-])/);
  }
});
