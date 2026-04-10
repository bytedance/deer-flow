import assert from "node:assert/strict";
import test from "node:test";

const { parseUploadedFiles } = await import(new URL("./utils.ts", import.meta.url).href);

void test("parses uploaded files blocks with type lines and human-readable sizes", () => {
  const files = parseUploadedFiles(`<uploaded_files>
The following files were uploaded in this message:

- titanic.csv (58.9 KB)
  Type: file
  Path: /mnt/user-data/uploads/titanic.csv

</uploaded_files>`);

  assert.deepEqual(files, [
    {
      filename: "titanic.csv",
      size: 60314,
      path: "/mnt/user-data/uploads/titanic.csv",
    },
  ]);
});

void test("parses filenames that contain parentheses", () => {
  const files = parseUploadedFiles(`<uploaded_files>
The following files were uploaded in this message:

- report (final).pdf (2.0 KB)
  Path: /mnt/user-data/uploads/report (final).pdf

</uploaded_files>`);

  assert.deepEqual(files, [
    {
      filename: "report (final).pdf",
      size: 2048,
      path: "/mnt/user-data/uploads/report (final).pdf",
    },
  ]);
});

void test("parses byte-sized uploaded files", () => {
  const files = parseUploadedFiles(`<uploaded_files>
The following files were uploaded in this message:

- note.txt (42 bytes)
  Path: /mnt/user-data/uploads/note.txt

</uploaded_files>`);

  assert.deepEqual(files, [
    {
      filename: "note.txt",
      size: 42,
      path: "/mnt/user-data/uploads/note.txt",
    },
  ]);
});
