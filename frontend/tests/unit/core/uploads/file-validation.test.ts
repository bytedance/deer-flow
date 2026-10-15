import { expect, test } from "@rstest/core";

import {
  MACOS_APP_BUNDLE_UPLOAD_MESSAGE,
  formatUploadSize,
  isLikelyMacOSAppBundle,
  splitUnsupportedUploadFiles,
  validateUploadLimits,
} from "@/core/uploads/file-validation";

const limits = {
  max_files: 2,
  max_file_size: 5,
  max_total_size: 7,
};

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

test("accepts a file at the per-file limit and rejects one byte over", () => {
  const atLimit = new File(["12345"], "at-limit.txt");
  const overLimit = new File(["123456"], "over-limit.txt");

  const result = validateUploadLimits([], [atLimit, overLimit], limits);

  expect(result.accepted).toEqual([atLimit]);
  expect(result.rejected).toEqual([overLimit]);
  expect(result.violations).toEqual([
    { code: "max_file_size", files: [overLimit], limit: 5 },
  ]);
});

test("counts existing files and their size before incoming files", () => {
  const existing = new File(["12"], "existing.txt");
  const accepted = new File(["12345"], "accepted.txt");
  const overCount = new File(["1"], "over-count.txt");

  const result = validateUploadLimits(
    [existing],
    [accepted, overCount],
    limits,
  );

  expect(result.accepted).toEqual([accepted]);
  expect(result.rejected).toEqual([overCount]);
  expect(result.violations[0]?.code).toBe("max_files");
});

test("keeps selection order and aggregates each violation category", () => {
  const first = new File(["1234"], "first.txt");
  const overSize = new File(["123456"], "over-size.txt");
  const overTotal = new File(["1234"], "over-total.txt");
  const second = new File(["1"], "second.txt");

  const result = validateUploadLimits(
    [],
    [first, overSize, overTotal, second],
    limits,
  );

  expect(result.accepted).toEqual([first, second]);
  expect(result.violations).toEqual([
    { code: "max_file_size", files: [overSize], limit: 5 },
    { code: "max_total_size", files: [overTotal], limit: 7 },
  ]);
});

test("does not block files when upload limits are unavailable", () => {
  const file = new File(["123456"], "fallback.txt");

  const result = validateUploadLimits([], [file]);

  expect(result.accepted).toEqual([file]);
  expect(result.rejected).toEqual([]);
  expect(result.violations).toEqual([]);
});

test("formats binary upload limits for display", () => {
  expect(formatUploadSize(50 * 1024 * 1024)).toBe("50 MiB");
  expect(formatUploadSize(1536)).toBe("1.5 KiB");
});
