import { afterEach, expect, test, rs } from "@rstest/core";

import {
  type PromptInputFilePart,
  promptInputFilePartToFile,
} from "@/core/uploads/prompt-input-files";

afterEach(() => {
  rs.restoreAllMocks();
  rs.unstubAllGlobals();
});

test("exports the prompt-input file conversion helper", () => {
  expect(typeof promptInputFilePartToFile).toBe("function");
});

test("reuses the original File when a prompt attachment already has one", async () => {
  const file = new File(["hello"], "note.txt", { type: "text/plain" });

  rs.stubGlobal(
    "fetch",
    rs.fn(() => {
      throw new Error("fetch should not run when File is already present");
    }),
  );

  const converted = await promptInputFilePartToFile({
    type: "file",
    filename: file.name,
    mediaType: file.type,
    url: "blob:http://localhost:2026/stale-preview-url",
    file,
  });

  expect(converted).toBe(file);
});

test("reconstructs a File from a data URL when no original File is present", async () => {
  const converted = await promptInputFilePartToFile({
    type: "file",
    filename: "note.txt",
    mediaType: "text/plain",
    url: "data:text/plain;base64,aGVsbG8=",
  });

  expect(converted).toBeTruthy();
  expect(converted!.name).toBe("note.txt");
  expect(converted!.type).toBe("text/plain");
  expect(await converted!.text()).toBe("hello");
});

test("rewraps the original File when the prompt metadata changes", async () => {
  const file = new File(["hello"], "note.txt", { type: "text/plain" });

  const converted = await promptInputFilePartToFile({
    type: "file",
    filename: "renamed.txt",
    mediaType: "text/markdown",
    file,
  } as PromptInputFilePart);

  expect(converted).toBeTruthy();
  expect(converted).not.toBe(file);
  expect(converted!.name).toBe("renamed.txt");
  expect(converted!.type).toBe("text/markdown");
  expect(await converted!.text()).toBe("hello");
});

test("returns null when upload preparation is missing required data", async () => {
  const converted = await promptInputFilePartToFile({
    type: "file",
    mediaType: "text/plain",
  } as PromptInputFilePart);

  expect(converted).toBeNull();
});

test("returns null when the URL fallback fetch fails", async () => {
  const warnSpy = rs.spyOn(console, "warn").mockImplementation(() => ({}));

  rs.stubGlobal(
    "fetch",
    rs.fn(async () => {
      throw new Error("network down");
    }),
  );

  const converted = await promptInputFilePartToFile({
    type: "file",
    filename: "note.txt",
    url: "blob:http://localhost:2026/missing-preview-url",
  } as PromptInputFilePart);

  expect(converted).toBeNull();
  expect(warnSpy).toHaveBeenCalledOnce();
});

test("returns null when the URL fallback fetch response is non-ok", async () => {
  const warnSpy = rs.spyOn(console, "warn").mockImplementation(() => ({}));

  rs.stubGlobal(
    "fetch",
    rs.fn(
      async () =>
        new Response("missing", {
          status: 404,
          statusText: "Not Found",
        }),
    ),
  );

  const converted = await promptInputFilePartToFile({
    type: "file",
    filename: "note.txt",
    url: "blob:http://localhost:2026/missing-preview-url",
  } as PromptInputFilePart);

  expect(converted).toBeNull();
  expect(warnSpy).toHaveBeenCalledOnce();
});
