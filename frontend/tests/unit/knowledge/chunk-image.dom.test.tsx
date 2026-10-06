/**
 * ChunkImage (2026-08-22 切片图片显示): MinerU 解析出的图片在 chunk markdown
 * 里是相对路径 `images/…`；卡片知道 kb/doc 时重写到 files 路由（真实图片），
 * 绝对/外部 URL 原样透传；加载失败降级为图注占位而非渲染器的通用裂图块。
 */
import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ChunkImage } from "@/components/workspace/knowledge/chunk-card";

afterEach(cleanup);

describe("ChunkImage", () => {
  it("rewrites relative refs to the document files route when kb/doc are known", () => {
    render(<ChunkImage alt="架构图" docId="doc-1" kbId="kb-1" src="images/p1.jpg" unavailableLabel="图片不可用" />);

    const img = screen.getByRole("img", { name: "架构图" });
    expect(img.getAttribute("src")).toContain("/api/knowledge-bases/kb-1/documents/doc-1/files/images/p1.jpg");
  });

  it("encodes each ref segment (non-ASCII filenames survive the rewrite)", () => {
    render(<ChunkImage alt="a" docId="doc 1" kbId="kb-1" src="images/图 1.png" unavailableLabel="图片不可用" />);

    const img = screen.getByRole("img");
    expect(img.getAttribute("src")).toContain(`/documents/${encodeURIComponent("doc 1")}/files/images/${encodeURIComponent("图 1.png")}`);
  });

  it("passes absolute/data/root URLs through untouched", () => {
    for (const src of ["https://cdn.example.com/a.png", "data:image/png;base64,AAAA", "/static/a.png"]) {
      const { unmount } = render(<ChunkImage alt="a" docId="doc-1" kbId="kb-1" src={src} unavailableLabel="图片不可用" />);
      expect(screen.getByRole("img").getAttribute("src")).toBe(src);
      unmount();
    }
  });

  it("keeps the raw ref when kb/doc context is missing (legacy callers degrade to the old behaviour)", () => {
    render(<ChunkImage alt="a" src="images/p1.jpg" unavailableLabel="图片不可用" />);

    expect(screen.getByRole("img").getAttribute("src")).toBe("images/p1.jpg");
  });

  it("degrades to the caption line on load error instead of a broken-image block", () => {
    render(<ChunkImage alt="图注：系统架构" docId="doc-1" kbId="kb-1" src="images/p1.jpg" unavailableLabel="图片不可用" />);

    fireEvent.error(screen.getByRole("img"));

    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText(/图片不可用/)).toBeTruthy();
    expect(screen.getByText(/图注：系统架构/)).toBeTruthy();
  });
});
