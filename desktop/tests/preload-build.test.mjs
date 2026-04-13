import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

void test("desktop build ships the handwritten CommonJS preload bundle", async () => {
  const [source, built] = await Promise.all([
    readFile(new URL("../preload/index.cjs", import.meta.url), "utf8"),
    readFile(new URL("../dist/preload/index.cjs", import.meta.url), "utf8"),
  ]);

  assert.equal(built, source);
});
