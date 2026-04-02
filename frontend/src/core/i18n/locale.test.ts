import assert from "node:assert/strict";
import test from "node:test";

const { DEFAULT_LOCALE, SUPPORTED_LOCALES, isLocale, normalizeLocale } =
  await import(new URL("./locale.ts", import.meta.url).href);

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

void test("normalizes Chinese browser locales to zh-CN", () => {
  assert.equal(normalizeLocale("zh-CN"), "zh-CN");
  assert.equal(normalizeLocale("zh"), "zh-CN");
  assert.equal(normalizeLocale("zh-TW"), "zh-CN");
  assert.equal(normalizeLocale("zh-HK"), "zh-CN");
});

void test("normalizes exact supported locales correctly", () => {
  assert.equal(normalizeLocale("en-US"), "en-US");
  assert.equal(normalizeLocale("zh-CN"), "zh-CN");
  assert.equal(normalizeLocale("pt-BR"), "pt-BR");
});

void test("falls back for undefined and empty string", () => {
  assert.equal(normalizeLocale(undefined), DEFAULT_LOCALE);
  assert.equal(normalizeLocale(""), DEFAULT_LOCALE);
});

void test("falls back for unsupported English variants", () => {
  // en-GB is not supported; no prefix rule for 'en'
  assert.equal(normalizeLocale("en-GB"), DEFAULT_LOCALE);
});

void test("isLocale returns true for supported locales", () => {
  assert.equal(isLocale("en-US"), true);
  assert.equal(isLocale("zh-CN"), true);
  assert.equal(isLocale("pt-BR"), true);
});

void test("isLocale returns false for unsupported values", () => {
  assert.equal(isLocale("fr-FR"), false);
  assert.equal(isLocale("pt"), false);
  assert.equal(isLocale(""), false);
});
