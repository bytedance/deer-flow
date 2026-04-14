import { expect, test } from "vitest";

import {
  MACOS_APP_BUNDLE_UPLOAD_MESSAGE,
  isLikelyMacOSAppBundle,
  splitUnsupportedUploadFiles,
} from "@/core/uploads/file-validation";

test("identifies Finder-style .app bundle uploads as unsupported", () => {
  expect(
    isLikelyMacOSAppBundle({
      name: "Vibe Island.app",
      type: "application/octet-stream",
    }),
  ).toBe(true);
});

test("keeps normal files and reports rejected app bundles", () => {
  const files = [
    new File(["demo"], "Vibe Island.app", {
      type: "application/octet-stream",
    }),
    new File(["notes"], "notes.txt", { type: "text/plain" }),
  ];

  const result = splitUnsupportedUploadFiles(files);

  expect(result.accepted.length).toBe(1);
  expect(result.accepted[0]?.name).toBe("notes.txt");
  expect(result.rejected.length).toBe(1);
  expect(result.rejected[0]?.name).toBe("Vibe Island.app");
  expect(result.message).toBe(MACOS_APP_BUNDLE_UPLOAD_MESSAGE);
});

test("treats empty MIME .app uploads as unsupported", () => {
  const result = splitUnsupportedUploadFiles([
    new File(["demo"], "Another.app", { type: "" }),
  ]);

  expect(result.accepted.length).toBe(0);
  expect(result.rejected.length).toBe(1);
  expect(result.message).toBe(MACOS_APP_BUNDLE_UPLOAD_MESSAGE);
});

test("returns no message when every file is supported", () => {
  const result = splitUnsupportedUploadFiles([
    new File(["notes"], "notes.txt", { type: "text/plain" }),
  ]);

  expect(result.accepted.length).toBe(1);
  expect(result.rejected.length).toBe(0);
  expect(result.message).toBeUndefined();
});
