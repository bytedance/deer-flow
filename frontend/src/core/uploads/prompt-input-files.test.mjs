import assert from "node:assert/strict";
import test from "node:test";

async function loadModule() {
  try {
    return await import("./prompt-input-files.ts");
  } catch (error) {
    return { error };
  }
}

test("exports the prompt-input file conversion helper", async () => {
  const loaded = await loadModule();

  assert.ok(
    !("error" in loaded),
    loaded.error instanceof Error
      ? loaded.error.message
      : "prompt-input-files module is missing",
  );
  assert.equal(typeof loaded.promptInputFilePartToFile, "function");
});

test("reuses the original File when a prompt attachment already has one", async () => {
  const { promptInputFilePartToFile } = await import("./prompt-input-files.ts");
  const file = new File(["hello"], "note.txt", { type: "text/plain" });
  const originalFetch = globalThis.fetch;

  globalThis.fetch = async () => {
    throw new Error("fetch should not run when File is already present");
  };

  try {
    const converted = await promptInputFilePartToFile({
      type: "file",
      filename: file.name,
      mediaType: file.type,
      url: "blob:http://localhost:2026/stale-preview-url",
      file,
    });

    assert.equal(converted, file);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("reconstructs a File from a data URL when no original File is present", async () => {
  const { promptInputFilePartToFile } = await import("./prompt-input-files.ts");
  const converted = await promptInputFilePartToFile({
    type: "file",
    filename: "note.txt",
    mediaType: "text/plain",
    url: "data:text/plain;base64,aGVsbG8=",
  });

  assert.ok(converted);
  assert.equal(converted.name, "note.txt");
  assert.equal(converted.type, "text/plain");
  assert.equal(await converted.text(), "hello");
});

test("rewraps the original File when the prompt metadata changes", async () => {
  const { promptInputFilePartToFile } = await import("./prompt-input-files.ts");
  const file = new File(["hello"], "note.txt", { type: "text/plain" });

  const converted = await promptInputFilePartToFile({
    type: "file",
    filename: "renamed.txt",
    mediaType: "text/markdown",
    file,
  });

  assert.ok(converted);
  assert.notEqual(converted, file);
  assert.equal(converted.name, "renamed.txt");
  assert.equal(converted.type, "text/markdown");
  assert.equal(await converted.text(), "hello");
});

test("returns null when upload preparation is missing required data", async () => {
  const { promptInputFilePartToFile } = await import("./prompt-input-files.ts");

  const converted = await promptInputFilePartToFile({
    type: "file",
    mediaType: "text/plain",
  });

  assert.equal(converted, null);
});

test("returns null when the URL fallback fetch fails", async () => {
  const { promptInputFilePartToFile } = await import("./prompt-input-files.ts");
  const originalFetch = globalThis.fetch;
  const originalWarn = console.warn;
  const warnCalls = [];

  console.warn = (...args) => {
    warnCalls.push(args);
  };

  globalThis.fetch = async () => {
    throw new Error("network down");
  };

  try {
    const converted = await promptInputFilePartToFile({
      type: "file",
      filename: "note.txt",
      url: "blob:http://localhost:2026/missing-preview-url",
    });

    assert.equal(converted, null);
    assert.equal(warnCalls.length, 1);
  } finally {
    globalThis.fetch = originalFetch;
    console.warn = originalWarn;
  }
});

test("returns null when the URL fallback fetch response is non-ok", async () => {
  const { promptInputFilePartToFile } = await import("./prompt-input-files.ts");
  const originalFetch = globalThis.fetch;
  const originalWarn = console.warn;
  const warnCalls = [];

  console.warn = (...args) => {
    warnCalls.push(args);
  };

  globalThis.fetch = async () =>
    new Response("missing", {
      status: 404,
      statusText: "Not Found",
    });

  try {
    const converted = await promptInputFilePartToFile({
      type: "file",
      filename: "note.txt",
      url: "blob:http://localhost:2026/missing-preview-url",
    });

    assert.equal(converted, null);
    assert.equal(warnCalls.length, 1);
  } finally {
    globalThis.fetch = originalFetch;
    console.warn = originalWarn;
  }
});
