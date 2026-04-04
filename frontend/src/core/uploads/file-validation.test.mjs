import assert from "node:assert/strict";
import test from "node:test";

import {
  MACOS_APP_BUNDLE_UPLOAD_MESSAGE,
  isLikelyMacOSAppBundle,
  splitUnsupportedUploadFiles,
} from "./file-validation.ts";

test("identifies Finder-style .app bundle uploads as unsupported", () => {
  assert.equal(
    isLikelyMacOSAppBundle({
      name: "Vibe Island.app",
      type: "application/octet-stream",
    }),
    true,
  );
});

test("keeps normal files and reports rejected app bundles", () => {
  const files = [
    new File(["demo"], "Vibe Island.app", {
      type: "application/octet-stream",
    }),
    new File(["notes"], "notes.txt", { type: "text/plain" }),
  ];

  const result = splitUnsupportedUploadFiles(files);

  assert.equal(result.accepted.length, 1);
  assert.equal(result.accepted[0]?.name, "notes.txt");
  assert.equal(result.rejected.length, 1);
  assert.equal(result.rejected[0]?.name, "Vibe Island.app");
  assert.equal(result.message, MACOS_APP_BUNDLE_UPLOAD_MESSAGE);
});

test("treats empty MIME .app uploads as unsupported", () => {
  const result = splitUnsupportedUploadFiles([
    new File(["demo"], "Another.app", { type: "" }),
  ]);

  assert.equal(result.accepted.length, 0);
  assert.equal(result.rejected.length, 1);
  assert.equal(result.message, MACOS_APP_BUNDLE_UPLOAD_MESSAGE);
});

test("returns no message when every file is supported", () => {
  const result = splitUnsupportedUploadFiles([
    new File(["notes"], "notes.txt", { type: "text/plain" }),
  ]);

  assert.equal(result.accepted.length, 1);
  assert.equal(result.rejected.length, 0);
  assert.equal(result.message, undefined);
});
