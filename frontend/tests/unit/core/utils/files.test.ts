import { expect, test } from "@rstest/core";
import { FilePlayIcon, FileTextIcon, ImageIcon } from "lucide-react";

import { canBrowserPreviewFile, getFileIcon } from "@/core/utils/files";

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
