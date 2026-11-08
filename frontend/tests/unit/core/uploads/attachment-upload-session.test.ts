import { expect, it, rs } from "@rstest/core";

import type { UploadResponse } from "@/core/uploads/api";
import { AttachmentUploadSession } from "@/core/uploads/attachment-upload-session";

const part = (name: string) => ({
  type: "file" as const,
  filename: name,
  mediaType: "text/plain",
  url: `blob:${name}`,
  file: new File([name], name, { type: "text/plain" }),
});
const response = (name: string): UploadResponse => ({
  success: true,
  files: [
    {
      filename: name,
      size: 5,
      path: name,
      virtual_path: `/uploads/${name}`,
      artifact_url: name,
    },
  ],
  message: "ok",
  skipped_files: [],
});

it("retains success, retries only the failed file and never conflates equal filenames", async () => {
  const first = part("same.txt"),
    second = part("same.txt");
  const upload = rs.fn(async (_thread: string, files: File[]) => {
    if (files[0] === second.file && upload.mock.calls.length <= 2)
      throw new Error("offline");
    return response(files[0]!.name);
  });
  const session = new AttachmentUploadSession(upload);
  await expect(session.uploadAll("thread", [first, second])).rejects.toThrow();
  expect(session.status(first)).toBe("uploaded");
  expect(session.status(second)).toBe("failed");
  await session.retry(second);
  expect(session.status(second)).toBe("uploaded");
  await session.uploadAll("thread", [first, second]);
  expect(upload).toHaveBeenCalledTimes(3);
});

it("ignores a cancelled request's late success and prevents cross-thread reuse", async () => {
  const file = part("one.txt");
  let resolve!: (result: UploadResponse) => void;
  const upload = rs.fn(
    () =>
      new Promise<UploadResponse>((done) => {
        resolve = done;
      }),
  );
  const session = new AttachmentUploadSession(upload);
  const pending = session.uploadAll("thread", [file]);
  await Promise.resolve();
  session.cancel(file);
  resolve(response("one.txt"));
  await expect(pending).rejects.toThrow();
  expect(session.status(file)).toBe("cancelled");
  await expect(session.uploadAll("other", [file])).rejects.toThrow(
    "thread changed",
  );
});

it("deactivation cancels uploads and rejects late submissions", async () => {
  const session = new AttachmentUploadSession();
  session.deactivate();
  await expect(session.uploadAll("thread", [part("one.txt")])).rejects.toThrow(
    "inactive",
  );
});
