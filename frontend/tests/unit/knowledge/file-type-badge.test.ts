/**
 * Suffix → icon category, mirrored row-for-row from frame 「01 分类色板与图标」
 * of the Ardot design file (720819382141740). The design is the authority: when
 * a suffix moves between categories there, the expectation here moves with it.
 *
 * Drag-in type probe (2026-09-01): MIME → badge kind recognition and the
 * accept/reject verdict computed while files hover the panel (dragover
 * exposes item types, so the empty-state nine-grid reacts before drop).
 */
import { describe, expect, it } from "@rstest/core";

import {
  type FileTypeKind,
  fileTypeKind,
  kindFromMime,
  probeDraggedItems,
  probeSignature,
} from "@/components/workspace/knowledge/file-type-badge";

const DESIGN_ROWS: [FileTypeKind, string[]][] = [
  ["word", ["doc", "docx", "wps", "pages", "rtf", "txt"]],
  ["sheet", ["xls", "xlsx", "csv", "tsv", "numbers", "et"]],
  ["ppt", ["ppt", "pptx", "key", "dps"]],
  ["pdf", ["pdf"]],
  ["code", ["md", "markdown", "json", "yaml", "xml", "py", "js", "sql"]],
  ["image", ["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp"]],
  ["media", ["mp4", "mov", "avi", "mkv", "mp3", "wav"]],
  ["archive", ["zip", "rar", "7z", "tar", "gz"]],
];

describe("fileTypeKind 按设计稿分类表映射后缀", () => {
  for (const [kind, suffixes] of DESIGN_ROWS) {
    it(`${kind}：${suffixes.join(" / ")}`, () => {
      for (const suffix of suffixes) {
        expect(fileTypeKind(`文档.${suffix}`)).toBe(kind);
      }
    });
  }

  it("决策①：Markdown 归「代码与数据」，不与 .docx 共用文档蓝", () => {
    expect(fileTypeKind("笔记.md")).toBe("code");
    expect(fileTypeKind("笔记.md")).not.toBe(fileTypeKind("规范.docx"));
  });

  it("后缀大小写与目录前缀不影响判定", () => {
    expect(fileTypeKind("REPORT.PDF")).toBe("pdf");
    expect(fileTypeKind("季度报告.Docx")).toBe("word");
    expect(fileTypeKind("a/b/c/readme.MARKDOWN")).toBe("code");
  });

  it("未知后缀与无后缀文件名走灰色兜底", () => {
    expect(fileTypeKind("未知.xyz")).toBe("unknown");
    expect(fileTypeKind("LICENSE")).toBe("unknown");
    // 前导点号是 dotfile 的后缀起点，不能当成 .gitignore 的类型信息
    expect(fileTypeKind(".gitignore")).toBe("unknown");
  });
});

const ALLOW = [".pdf", ".md", ".txt", ".docx"];

function item(type: string) {
  return { kind: "file", type };
}

describe("kindFromMime", () => {
  it("maps common document MIME types to their badge kind", () => {
    expect(kindFromMime("application/pdf")).toBe("pdf");
    expect(kindFromMime("application/vnd.openxmlformats-officedocument.wordprocessingml.document")).toBe("word");
    expect(kindFromMime("text/plain")).toBe("word");
    expect(kindFromMime("text/markdown")).toBe("code");
    expect(kindFromMime("text/tab-separated-values")).toBe("sheet");
    expect(kindFromMime("application/zip")).toBe("archive");
  });

  it("prefix-matches image/audio/video families", () => {
    expect(kindFromMime("image/png")).toBe("image");
    expect(kindFromMime("video/mp4")).toBe("media");
    expect(kindFromMime("audio/mpeg")).toBe("media");
  });

  it("returns null for empty or unknown MIME types", () => {
    expect(kindFromMime("")).toBeNull();
    expect(kindFromMime("application/x-msdownload")).toBeNull();
  });
});

describe("probeDraggedItems", () => {
  it("lights the kinds of accepted files", () => {
    const probe = probeDraggedItems([item("application/pdf")], ALLOW);
    expect(probe.litKinds).toEqual(["pdf"]);
    expect(probe.anyAccepted).toBe(true);
    expect(probe.anyRejected).toBe(false);
  });

  it("flags rejection when no dragged file matches the allowlist", () => {
    const probe = probeDraggedItems([item("application/x-msdownload")], ALLOW);
    expect(probe.litKinds).toEqual([]);
    expect(probe.anyAccepted).toBe(false);
    expect(probe.anyRejected).toBe(true);
  });

  it("handles mixed batches: accepted kinds light, rejection still flagged", () => {
    const probe = probeDraggedItems(
      [item("application/pdf"), item("application/zip")],
      ALLOW,
    );
    expect(probe.litKinds).toEqual(["pdf"]);
    expect(probe.anyAccepted).toBe(true);
    expect(probe.anyRejected).toBe(true);
  });

  it("ignores non-file items and empty drags", () => {
    expect(probeDraggedItems(null, ALLOW).anyAccepted).toBe(false);
    const probe = probeDraggedItems([{ kind: "string", type: "text/plain" }], ALLOW);
    expect(probe.anyAccepted).toBe(false);
    expect(probe.anyRejected).toBe(false);
  });

  it("treats an unrecognized MIME as rejected (better safe than lit)", () => {
    const probe = probeDraggedItems([item("")], ALLOW);
    expect(probe.anyAccepted).toBe(false);
    expect(probe.anyRejected).toBe(true);
  });
});

describe("probeSignature", () => {
  it("distinguishes probes so dragover storms only re-render on change", () => {
    const a = probeDraggedItems([item("application/pdf")], ALLOW);
    const b = probeDraggedItems([item("application/pdf")], ALLOW);
    const c = probeDraggedItems([item("application/zip")], ALLOW);
    expect(probeSignature(a)).toBe(probeSignature(b));
    expect(probeSignature(a)).not.toBe(probeSignature(c));
    expect(probeSignature(null)).toBe("");
  });
});
