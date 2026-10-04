import { expect, test } from "@rstest/core";
import { FilePlayIcon, FileTextIcon, ImageIcon } from "lucide-react";

import {
  canBrowserPreviewFile,
  checkCodeFile,
  getFileIcon,
} from "@/core/utils/files";

test.each([
  ["animation.apng", ImageIcon],
  ["photo.avif", ImageIcon],
  ["clip.webm", FilePlayIcon],
])("uses a media icon for previewable %s", (filepath, icon) => {
  expect(canBrowserPreviewFile(filepath)).toBe(true);
  expect(getFileIcon(filepath).type).toBe(icon);
});

test("keeps the document icon for an unknown extension", () => {
  expect(getFileIcon("data.unknown").type).toBe(FileTextIcon);
});

test.each(["constructor", "data.constructor", "__proto__", "data.__proto__"])(
  "does not classify inherited map properties as languages for %s",
  (filename) => {
    expect(checkCodeFile(`/mnt/user-data/outputs/${filename}`)).toEqual({
      isCodeFile: false,
      language: null,
    });
    expect(getFileIcon(filename).type).toBe(FileTextIcon);
  },
);

// `extensionMap` maps a file extension to a language name. Both halves of that
// direction matter: `checkCodeFile` tests extension membership, and the language
// is what the editor and previewers receive.
test("resolves a language from its extension", () => {
  expect(checkCodeFile("script.hs")).toEqual({
    isCodeFile: true,
    language: "haskell",
  });
  expect(checkCodeFile("deploy.ex")).toEqual({
    isCodeFile: true,
    language: "elixir",
  });
  expect(checkCodeFile("analysis.jl")).toEqual({
    isCodeFile: true,
    language: "julia",
  });
});

test("values the language name, never the extension it came from", () => {
  expect(checkCodeFile("notes.julia")).toEqual({
    isCodeFile: true,
    language: "julia",
  });
});
