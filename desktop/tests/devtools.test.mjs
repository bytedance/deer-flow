import assert from "node:assert/strict";
import test from "node:test";

const { getDevtoolsAccelerators } = await import(
  "../dist/main/devtools-accelerators.js"
);

void test("getDevtoolsAccelerators includes standard macOS shortcuts", () => {
  assert.deepEqual(getDevtoolsAccelerators("darwin"), [
    "F12",
    "CommandOrControl+Shift+I",
  ]);
});

void test("getDevtoolsAccelerators includes standard non-macOS shortcuts", () => {
  assert.deepEqual(getDevtoolsAccelerators("win32"), [
    "F12",
    "Control+Shift+I",
  ]);
});
