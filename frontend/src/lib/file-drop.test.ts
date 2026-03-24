import assert from "node:assert/strict";
import test from "node:test";

type DesktopDroppedFile = {
  bytes: number[];
  mimeType?: string | null;
  name: string;
  path: string;
};

type FileDropModule = {
  filterDroppedPaths: (paths: readonly string[]) => string[];
  resolveDesktopDroppedFiles: (
    paths: readonly string[],
    options?: {
      isDesktop?: () => boolean;
      loadDroppedFiles?: (
        paths: string[],
      ) => Promise<readonly DesktopDroppedFile[]>;
    },
  ) => Promise<File[]>;
  shouldSuppressBrowserDrop: (
    lastNativeDropAt: number | null | undefined,
    now?: number,
    windowMs?: number,
  ) => boolean;
};

const fileDropModuleUrl = new URL("./file-drop.ts", import.meta.url).href;
const {
  filterDroppedPaths,
  resolveDesktopDroppedFiles,
  shouldSuppressBrowserDrop,
} = (await import(fileDropModuleUrl)) as FileDropModule;

void test("filterDroppedPaths removes blanks and duplicate native paths", () => {
  assert.deepEqual(
    filterDroppedPaths([
      "C:\\Users\\dev\\Desktop\\notes.md",
      "",
      "  ",
      "C:\\Users\\dev\\Desktop\\notes.md",
      "C:\\Users\\dev\\Desktop\\diagram.png",
    ]),
    [
      "C:\\Users\\dev\\Desktop\\notes.md",
      "C:\\Users\\dev\\Desktop\\diagram.png",
    ],
  );
});

void test(
  "resolveDesktopDroppedFiles is a safe no-op outside desktop mode",
  async () => {
    let loadAttempts = 0;

    const files = await resolveDesktopDroppedFiles(["C:\\Users\\dev\\notes.md"], {
      isDesktop: () => false,
      loadDroppedFiles: async (paths) => {
        loadAttempts += 1;
        return paths.map((path) => ({
          bytes: [65],
          name: path.split("\\").at(-1) ?? "notes.md",
          path,
        }));
      },
    });

    assert.deepEqual(files, []);
    assert.equal(loadAttempts, 0);
  },
);

void test(
  "resolveDesktopDroppedFiles maps native payloads into the existing File[] shape",
  async () => {
    let requestedPaths: string[] = [];

    const files = await resolveDesktopDroppedFiles(
      [
        "C:\\Users\\dev\\Desktop\\notes.md",
        "C:\\Users\\dev\\Desktop\\diagram.png",
      ],
      {
        isDesktop: () => true,
        loadDroppedFiles: async (paths) => {
          requestedPaths = paths;

          return [
            {
              bytes: [72, 101, 108, 108, 111],
              name: "notes.md",
              path: paths[0]!,
            },
            {
              bytes: [137, 80, 78, 71],
              name: "diagram.png",
              path: paths[1]!,
            },
          ];
        },
      },
    );

    assert.deepEqual(requestedPaths, [
      "C:\\Users\\dev\\Desktop\\notes.md",
      "C:\\Users\\dev\\Desktop\\diagram.png",
    ]);
    assert.equal(files.length, 2);
    assert.equal(files[0]?.name, "notes.md");
    assert.equal(files[0]?.type, "text/markdown");
    assert.equal(await files[0]?.text(), "Hello");
    assert.equal(files[1]?.name, "diagram.png");
    assert.equal(files[1]?.type, "image/png");
  },
);

void test("shouldSuppressBrowserDrop only blocks the immediate duplicate DOM drop", () => {
  assert.equal(shouldSuppressBrowserDrop(null, 1_000), false);
  assert.equal(shouldSuppressBrowserDrop(1_000, 1_120), true);
  assert.equal(shouldSuppressBrowserDrop(1_000, 1_301), false);
  assert.equal(shouldSuppressBrowserDrop(1_000, 1_450, 500), true);
});
