import assert from "node:assert/strict";
import test from "node:test";

const { DEFAULT_LOCALE, SUPPORTED_LOCALES, normalizeLocale } = await import(
  new URL("./locale.ts", import.meta.url).href
);

void test("registers pt-BR as a supported locale", () => {
  assert.deepEqual(SUPPORTED_LOCALES, ["en-US", "zh-CN", "pt-BR"]);
});

void test("normalizes Portuguese browser locales to pt-BR", () => {
  assert.equal(normalizeLocale("pt-BR"), "pt-BR");
  assert.equal(normalizeLocale("pt"), "pt-BR");
  assert.equal(normalizeLocale("pt-PT"), "pt-BR");
});

void test("falls back to default locale for unsupported values", () => {
  assert.equal(normalizeLocale("fr-FR"), DEFAULT_LOCALE);
  assert.equal(normalizeLocale(null), DEFAULT_LOCALE);
});
