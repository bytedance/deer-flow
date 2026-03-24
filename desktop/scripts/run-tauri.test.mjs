import assert from "node:assert/strict";
import test from "node:test";

const moduleUrl = new URL("./run-tauri.mjs", import.meta.url);
const { buildPathWithCargoCandidates, getCargoBinCandidates, isDirectExecution } = await import(moduleUrl);

void test("getCargoBinCandidates prefers CARGO_HOME before the default user cargo directory", () => {
  const candidates = getCargoBinCandidates({
    env: {
      CARGO_HOME: "C:\\custom-cargo",
      USERPROFILE: "C:\\Users\\Administrator",
    },
    platform: "win32",
  });

  assert.deepEqual(candidates, [
    "C:\\custom-cargo\\bin",
    "C:\\Users\\Administrator\\.cargo\\bin",
  ]);
});

void test("buildPathWithCargoCandidates prepends a discovered cargo bin when PATH is missing it", () => {
  const nextPath = buildPathWithCargoCandidates({
    env: {
      USERPROFILE: "C:\\Users\\Administrator",
      PATH: "C:\\Windows\\System32",
    },
    platform: "win32",
    pathDelimiter: ";",
    hasCargoExecutable(candidate) {
      return candidate === "C:\\Users\\Administrator\\.cargo\\bin";
    },
  });

  assert.equal(nextPath, "C:\\Users\\Administrator\\.cargo\\bin;C:\\Windows\\System32");
});

void test("buildPathWithCargoCandidates leaves PATH unchanged when cargo is already reachable", () => {
  const nextPath = buildPathWithCargoCandidates({
    env: {
      USERPROFILE: "C:\\Users\\Administrator",
      PATH: "C:\\Users\\Administrator\\.cargo\\bin;C:\\Windows\\System32",
    },
    platform: "win32",
    pathDelimiter: ";",
    hasCargoExecutable() {
      return true;
    },
  });

  assert.equal(nextPath, "C:\\Users\\Administrator\\.cargo\\bin;C:\\Windows\\System32");
});

void test("isDirectExecution matches the current script path on Windows-style argv input", () => {
  assert.equal(
    isDirectExecution({
      argv1: "G:\\deer-flow\\deer-flow\\desktop\\scripts\\run-tauri.mjs",
      moduleUrl: "file:///G:/deer-flow/deer-flow/desktop/scripts/run-tauri.mjs",
    }),
    true,
  );
});
