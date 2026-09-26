import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { expect, it } from "@rstest/core";

it("resolves formatter configuration in checkouts containing spaces and Unicode", () => {
  const root = mkdtempSync(path.join(tmpdir(), "deerflow 清单 space-"));
  try {
    const frontend = path.join(root, "frontend");
    const scripts = path.join(frontend, "scripts");
    const backend = path.join(
      root,
      "backend/packages/harness/deerflow/capabilities",
    );
    const output = path.join(frontend, "src/core/capabilities");
    for (const directory of [scripts, backend, output])
      mkdirSync(directory, { recursive: true });
    writeFileSync(path.join(frontend, "package.json"), '{"type":"module"}');
    writeFileSync(
      path.join(frontend, ".prettierrc.json"),
      '{"tabWidth":7,"printWidth":20}',
    );
    writeFileSync(
      path.join(backend, "builtin.json"),
      '[{"id":"example","adapter":"business"}]',
    );
    symlinkSync(
      path.resolve("node_modules"),
      path.join(frontend, "node_modules"),
      "junction",
    );
    const script = path.join(scripts, "sync-capability-catalog.mjs");
    copyFileSync(path.resolve("scripts/sync-capability-catalog.mjs"), script);
    execFileSync(process.execPath, [script], { cwd: frontend, timeout: 10000 });
    const snapshot = readFileSync(
      path.join(output, "builtin.demo.json"),
      "utf8",
    );
    expect(JSON.parse(snapshot)).toEqual([
      { id: "example", adapter: "business" },
    ]);
    expect(snapshot.startsWith("[\n       {\n")).toBe(true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
