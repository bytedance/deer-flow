import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

void test("settings models title no longer mentions API keys", async () => {
  const [zh, en] = await Promise.all([
    readFile(new URL("../src/core/i18n/locales/zh-CN.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/core/i18n/locales/en-US.ts", import.meta.url), "utf8"),
  ]);

  assert.match(zh, /title:\s*"模型"/);
  assert.doesNotMatch(zh, /title:\s*"模型与 API Key"/);
  assert.match(en, /title:\s*"Models"/);
  assert.doesNotMatch(en, /title:\s*"Models & API Keys"/);
});
