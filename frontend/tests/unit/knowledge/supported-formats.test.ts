/**
 * Upload allowlist helpers (phase-2 batch-1 Task 6, spec §6): suffix
 * partition for the pre-upload intercept, the file-picker accept attribute
 * builder, and the fallback constant mirroring the backend endpoint.
 */
import { describe, expect, it } from "@rstest/core";

import {
  acceptAttribute,
  FALLBACK_SUPPORTED_SUFFIXES,
  fileSuffix,
  partitionFilesBySuffix,
} from "@/core/knowledge/supported-formats";

describe("fileSuffix", () => {
  it("extracts the lowercase dotted suffix", () => {
    expect(fileSuffix("手册.PDF")).toBe(".pdf");
    expect(fileSuffix("archive.tar.gz")).toBe(".gz");
  });

  it("returns empty for names without a real extension", () => {
    expect(fileSuffix("noext")).toBe("");
    expect(fileSuffix(".hidden")).toBe(""); // dotfile: no suffix (Path.suffix parity)
  });
});

describe("partitionFilesBySuffix", () => {
  it("splits accepted and rejected files case-insensitively", () => {
    const files = [{ name: "a.md" }, { name: "evil.EXE" }, { name: "笔记.TXT" }, { name: "noext" }];
    const { accepted, rejected } = partitionFilesBySuffix(files, [".md", ".txt"]);
    expect(accepted.map((f) => f.name)).toEqual(["a.md", "笔记.TXT"]);
    expect(rejected.map((f) => f.name)).toEqual(["evil.EXE", "noext"]);
  });

  it("accepts everything when the suffixes are the full allowlist", () => {
    const files = [{ name: "手册.pdf" }, { name: "数据.csv" }];
    const { accepted, rejected } = partitionFilesBySuffix(files, FALLBACK_SUPPORTED_SUFFIXES);
    expect(accepted).toHaveLength(2);
    expect(rejected).toHaveLength(0);
  });
});

describe("acceptAttribute", () => {
  it("builds a sorted comma-separated accept string", () => {
    expect(acceptAttribute([".md", ".csv", ".txt"])).toBe(".csv,.md,.txt");
  });
});

describe("FALLBACK_SUPPORTED_SUFFIXES", () => {
  it("mirrors the backend spec §6 allowlist (+ table suffixes, spec 2026-09-09 §4)", () => {
    expect([...FALLBACK_SUPPORTED_SUFFIXES].sort()).toEqual([
      ".csv",
      ".doc",
      ".docx",
      ".jpeg",
      ".jpg",
      ".markdown",
      ".md",
      ".pdf",
      ".png",
      ".ppt",
      ".pptx",
      ".tsv",
      ".txt",
      ".xls",
      ".xlsx",
    ]);
  });

  it("includes the spreadsheet suffixes gated by rag.table.enabled (spec 2026-09-09 §4)", () => {
    // 后端 /supported-formats 端点是真源；fallback 仅镜像，用于端点未达时的客户端守卫。
    for (const suffix of [".xlsx", ".xls", ".tsv"]) {
      expect(FALLBACK_SUPPORTED_SUFFIXES).toContain(suffix);
    }
  });
});
