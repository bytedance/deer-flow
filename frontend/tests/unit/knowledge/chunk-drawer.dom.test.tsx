/**
 * Shared read-only chunk display (spec §3.6 切片可视化 / §4.6 引用展开):
 * the same card renders drawer chunks (full metadata) and citation-expanded
 * chunks (doc name + text). The drawer paginates through the chunks endpoint.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { useQuery } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";

rs.mock("@tanstack/react-query", () => ({
  useQuery: rs.fn(),
}));

rs.mock("@/core/knowledge/hooks", () => ({
  knowledgeChunksKey: rs.fn(),
  useUpdateChunk: rs.fn(),
  usePreviewChunkDeletion: rs.fn(),
  useReExtractChunk: rs.fn(),
  useDeleteChunk: rs.fn(),
}));

rs.mock("sonner", () => ({
  toast: { error: rs.fn(), success: rs.fn(), info: rs.fn(), warning: rs.fn() },
}));

import { ChunkCard } from "@/components/workspace/knowledge/chunk-card";
import { ChunkDrawer } from "@/components/workspace/knowledge/chunk-drawer";
import { KB_TOASTER_ID } from "@/components/workspace/knowledge/kb-toast";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { knowledgeChunksKey, useDeleteChunk, usePreviewChunkDeletion, useReExtractChunk, useUpdateChunk } from "@/core/knowledge/hooks";
import type { KnowledgeChunk, KnowledgeDocument } from "@/core/knowledge/types";

const CHUNK: KnowledgeChunk = {
  chunk_id: "doc-1#0000",
  doc_id: "doc-1",
  kb_id: "kb-1",
  chunk_index: 0,
  text: "知识库系统将非结构化文档转化为可检索的知识资产。",
  heading_path: ["第一章", "1.1 目标"],
  page: 3,
  token_count: 512,
  entities: ["DeerFlow", "Gateway"],
  extract_status: "done",
  last_edited_at: null,
};

const DOC: KnowledgeDocument = {
  id: "doc-1",
  kb_id: "kb-1",
  uploader_id: "user-1",
  name: "产品手册.pdf",
  size_bytes: 2048,
  storage_path: "p",
  status: "ready",
  progress_percent: 100,
  chunk_count: 2,
  error: null,
  path_status: null,
  content_hash: null,
  created_at: "2026-08-09T10:00:00Z",
};

function renderWithI18n(node: React.ReactNode) {
  return render(
    <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
      {node}
    </I18nContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("ChunkCard", () => {
  it("renders text with heading path, page, tokens, and entities", () => {
    renderWithI18n(<ChunkCard text={CHUNK.text} headingPath={CHUNK.heading_path} page={CHUNK.page} tokenCount={CHUNK.token_count} entities={CHUNK.entities} />);
    expect(screen.getByText(CHUNK.text)).toBeTruthy();
    expect(screen.getByText(/第一章/)).toBeTruthy();
    expect(screen.getByText(/1\.1 目标/)).toBeTruthy();
    expect(screen.getByText(/3/)).toBeTruthy();
    expect(screen.getByText(/512/)).toBeTruthy();
    expect(screen.getByText("DeerFlow")).toBeTruthy();
    expect(screen.getByText("Gateway")).toBeTruthy();
  });

  it("renders the citation form (doc name + text) without drawer-only metadata", () => {
    renderWithI18n(<ChunkCard docName="产品手册.pdf" text={CHUNK.text} page={2} />);
    expect(screen.getByText(/产品手册\.pdf/)).toBeTruthy();
    expect(screen.getByText(CHUNK.text)).toBeTruthy();
  });

  it("lets the entity badge row wrap so many long entities never overflow the card", () => {
    // Production repro: six long entity badges (知识库 RAG 一期 / 三路索引 /
    // 三栏工作台 / …) rendered on ONE nowrap flex line and spilled past the
    // card boundary; the 实体: label got squeezed into a vertical column.
    const many = ["知识库 RAG 一期", "三路索引", "三栏工作台", "多租户共享与权限", "召回测试与评估面板", "图谱可视化探索"];
    renderWithI18n(<ChunkCard text={CHUNK.text} entities={many} />);
    const label = screen.getByText(/实体/);
    expect(label.className).toContain("shrink-0");
    expect(label.parentElement!.className).toContain("flex-wrap");
  });
});

describe("ChunkDrawer", () => {
  it("loads and renders the first chunk page when opened", async () => {
    rs.mocked(knowledgeChunksKey).mockReturnValue(["knowledge-bases", "kb-1", "documents", "doc-1", "chunks", { offset: 0, limit: 50 }]);
    rs.mocked(useQuery).mockReturnValue({
      data: { items: [CHUNK], total: 1, offset: 0, limit: 50 },
      isLoading: false,
    } as never);
    rs.mocked(useUpdateChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(usePreviewChunkDeletion).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useReExtractChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useDeleteChunk).mockReturnValue({ mutateAsync: rs.fn(), isPending: false } as never);

    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);

    expect(await screen.findByText(CHUNK.text)).toBeTruthy();
    expect(rs.mocked(knowledgeChunksKey).mock.calls[0]?.slice(0, 2)).toEqual(["kb-1", "doc-1"]);
    // 切片导航（2026-09-05）：抽屉传入 index 后卡片头部显示 #N 序号
    expect(screen.getByText("#1")).toBeTruthy();
    // no second page → no load-more button
    expect(screen.queryByRole("button", { name: "加载更多" })).toBeNull();
  });

  it("numbers cards by list position so chunk_index gaps never leak into #N (2026-09-05)", async () => {
    // 复现实习.jpg：单切片但 chunk_index=1（历史删除留下的空洞）——卡片序号
    // 取列表位置 #1，与头部「当前 #K」、刻度轨同一坐标系，不显 #2。
    const gapped = { ...CHUNK, chunk_id: "doc-1#0001", chunk_index: 1 };
    rs.mocked(knowledgeChunksKey).mockReturnValue(["knowledge-bases", "kb-1", "documents", "doc-1", "chunks", { offset: 0, limit: 50 }]);
    rs.mocked(useQuery).mockReturnValue({
      data: { items: [gapped], total: 1, offset: 0, limit: 50 },
      isLoading: false,
    } as never);
    rs.mocked(useUpdateChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(usePreviewChunkDeletion).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useReExtractChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useDeleteChunk).mockReturnValue({ mutateAsync: rs.fn(), isPending: false } as never);

    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);

    expect(await screen.findByText(CHUNK.text)).toBeTruthy();
    expect(screen.getByText("#1")).toBeTruthy();
    expect(screen.queryByText("#2")).toBeNull();
  });

  it("auto-loads every chunk when total is within the full-load cap", async () => {
    rs.mocked(knowledgeChunksKey).mockReturnValue(["knowledge-bases", "kb-1", "documents", "doc-1", "chunks", { offset: 0, limit: 20 }]);
    rs.mocked(useQuery).mockReturnValue({
      data: { items: [CHUNK], total: 50, offset: 0, limit: 20 },
      isLoading: false,
    } as never);
    rs.mocked(useUpdateChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(usePreviewChunkDeletion).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useReExtractChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useDeleteChunk).mockReturnValue({ mutateAsync: rs.fn(), isPending: false } as never);

    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);

    // 50 ≤ FULL_LOAD_CAP(300) → limit grows to total without user interaction
    await waitFor(() => expect(rs.mocked(knowledgeChunksKey).mock.calls.at(-1)![3]).toBe(50));
  });

  it("paginates through 加载更多 when total exceeds the full-load cap", async () => {
    rs.mocked(knowledgeChunksKey).mockReturnValue(["knowledge-bases", "kb-1", "documents", "doc-1", "chunks", { offset: 0, limit: 1 }]);
    rs.mocked(useQuery).mockReturnValue({
      data: { items: [CHUNK], total: 350, offset: 0, limit: 1 },
      isLoading: false,
    } as never);
    rs.mocked(useUpdateChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(usePreviewChunkDeletion).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useReExtractChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useDeleteChunk).mockReturnValue({ mutateAsync: rs.fn(), isPending: false } as never);

    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);

    // 刻度轨（total > 1）渲染窗口化刻度按钮，aria 带序号
    expect(await screen.findByRole("button", { name: "切片 #1" })).toBeTruthy();

    fireEvent.click(await screen.findByRole("button", { name: "加载更多" }));
    const calls = rs.mocked(knowledgeChunksKey).mock.calls;
    // growing-limit pagination: same offset, larger limit on the next request
    expect(calls.at(-1)![2]).toBe(calls[0]![2]);
    expect(calls.at(-1)![3]).toBeGreaterThan(calls[0]![3]);
  });

  it("confirm delete runs the real cascade delete (Task 5 收尾)", async () => {
    rs.mocked(knowledgeChunksKey).mockReturnValue(["knowledge-bases", "kb-1", "documents", "doc-1", "chunks", { offset: 0, limit: 50 }]);
    rs.mocked(useQuery).mockReturnValue({
      data: { items: [CHUNK], total: 1, offset: 0, limit: 50 },
      isLoading: false,
    } as never);
    rs.mocked(useUpdateChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    const previewAsync = rs
      .fn()
      .mockResolvedValue({ orphaned_entities: ["Qdrant"], affected_entities: ["DeerFlow"], relation_deletions: [] });
    rs.mocked(usePreviewChunkDeletion).mockReturnValue({ mutateAsync: previewAsync } as never);
    rs.mocked(useReExtractChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    const deleteAsync = rs.fn().mockResolvedValue(undefined);
    rs.mocked(useDeleteChunk).mockReturnValue({ mutateAsync: deleteAsync, isPending: false } as never);

    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);

    // Card delete button → preview dialog with the impact lists.
    fireEvent.click(await screen.findByRole("button", { name: "删除" }));
    expect(await screen.findByText("删除预览")).toBeTruthy();
    expect(previewAsync).toHaveBeenCalledWith({ chunk_ids: [CHUNK.chunk_id] });

    // Confirm → the real DELETE mutation fires with the remembered target.
    fireEvent.click(await screen.findByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(deleteAsync).toHaveBeenCalledWith(CHUNK.chunk_id));
    expect(toast.success).toHaveBeenCalledWith("切片已删除", expect.objectContaining({ toasterId: KB_TOASTER_ID }));
  });

  it("shows the empty-state copy when the document has no chunks", async () => {
    rs.mocked(knowledgeChunksKey).mockReturnValue(["knowledge-bases", "kb-1", "documents", "doc-1", "chunks", { offset: 0, limit: 50 }]);
    rs.mocked(useQuery).mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 50 },
      isLoading: false,
    } as never);
    rs.mocked(useUpdateChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(usePreviewChunkDeletion).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useReExtractChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useDeleteChunk).mockReturnValue({ mutateAsync: rs.fn(), isPending: false } as never);

    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);

    expect(await screen.findByText("该文档还没有切片")).toBeTruthy();
  });

  it("focusChunkId 定位目标切片并同步 active 徽章（2026-09-05 检索测试跳转）", async () => {
    const second: KnowledgeChunk = {
      ...CHUNK,
      chunk_id: "doc-1#0001",
      chunk_index: 1,
      text: "第二章的切片正文。",
      heading_path: ["第二章"],
    };
    rs.mocked(knowledgeChunksKey).mockReturnValue(["knowledge-bases", "kb-1", "documents", "doc-1", "chunks", { offset: 0, limit: 50 }]);
    rs.mocked(useQuery).mockReturnValue({
      data: { items: [CHUNK, second], total: 2, offset: 0, limit: 50 },
      isLoading: false,
    } as never);
    rs.mocked(useUpdateChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(usePreviewChunkDeletion).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useReExtractChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
    rs.mocked(useDeleteChunk).mockReturnValue({ mutateAsync: rs.fn(), isPending: false } as never);

    renderWithI18n(
      <ChunkDrawer kbId="kb-1" doc={DOC} open focusChunkId="doc-1#0001" onOpenChange={() => undefined} />,
    );

    expect(await screen.findByText("第二章的切片正文。")).toBeTruthy();
    // 位置同步：头部「当前」徽章直接置到 #2（不等 smooth 滚动落定）
    expect(screen.getByText("当前 #2")).toBeTruthy();
  });
});

// ── 视频镜头时间码芯片 + 缩略图（spec 2026-09-08 §5，plan Task 10）──────────
// 视频 chunk（后端 chunks 端点 join video_shots 注入 media/shot_index/start_ms/
// end_ms/frame_url）在卡片上方渲染 mono 时间码芯片 + lazy 关键帧缩略图（404/缺帧
// 降级图标）+「复制时间码」按钮（走 kb-toast 中栏作用域）。芯片/缩略图的 seek 播放
// 语义是 Task 10b，本任务只做展示 + 复制。
function mockChunks(items: KnowledgeChunk[], total = items.length) {
  rs.mocked(knowledgeChunksKey).mockReturnValue(["knowledge-bases", "kb-1", "documents", "doc-1", "chunks", { offset: 0, limit: 50 }]);
  rs.mocked(useQuery).mockReturnValue({ data: { items, total, offset: 0, limit: 50 }, isLoading: false } as never);
  rs.mocked(useUpdateChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
  rs.mocked(usePreviewChunkDeletion).mockReturnValue({ mutateAsync: rs.fn() } as never);
  rs.mocked(useReExtractChunk).mockReturnValue({ mutateAsync: rs.fn() } as never);
  rs.mocked(useDeleteChunk).mockReturnValue({ mutateAsync: rs.fn(), isPending: false } as never);
}

const VIDEO_CHUNK: KnowledgeChunk = {
  ...CHUNK,
  chunk_id: "doc-1#0000",
  text: "场景：讲师开场\n口述：大家好\n屏幕文字：（无）",
  media: "video",
  shot_index: 0,
  start_ms: 72_000, // 00:01:12
  end_ms: 100_000, // 00:01:40
  frame_url: "/api/knowledge-bases/kb-1/documents/doc-1/shots/0/frame",
};

describe("ChunkDrawer 视频时间码芯片 + 缩略图（spec 2026-09-08 §5）", () => {
  it("视频 chunk 渲染 mono 时间码芯片 #K · HH:MM:SS–HH:MM:SS", async () => {
    mockChunks([VIDEO_CHUNK]);
    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);
    const chip = await screen.findByTestId("timecode-chip");
    expect(chip.textContent).toContain("#1");
    expect(chip.textContent).toContain("00:01:12–00:01:40");
    expect(chip.className).toContain("font-mono");
  });

  it("有 frame_url 时渲染 lazy 关键帧缩略图，src 指向 shots/{i}/frame", async () => {
    mockChunks([VIDEO_CHUNK]);
    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);
    const thumb = await screen.findByTestId("shot-thumbnail");
    expect(thumb.getAttribute("src")).toContain("documents/doc-1/shots/0/frame");
    expect(thumb.getAttribute("loading")).toBe("lazy");
  });

  it("缩略图 404（onError）降级为缺图图标", async () => {
    mockChunks([VIDEO_CHUNK]);
    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);
    const thumb = await screen.findByTestId("shot-thumbnail");
    fireEvent.error(thumb);
    expect(await screen.findByTestId("shot-thumbnail-missing")).toBeTruthy();
    expect(screen.queryByTestId("shot-thumbnail")).toBeNull();
  });

  it("缺帧镜头（无 frame_url）直接渲染缺图图标，不渲染 img", async () => {
    mockChunks([{ ...VIDEO_CHUNK, frame_url: undefined }]);
    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);
    expect(await screen.findByTestId("shot-thumbnail-missing")).toBeTruthy();
    expect(screen.queryByTestId("shot-thumbnail")).toBeNull();
  });

  it("「复制时间码」按钮写剪贴板并走 kb-toast 中栏作用域（带 toasterId）", async () => {
    const writeText = rs.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true, writable: true });
    mockChunks([VIDEO_CHUNK]);
    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);
    fireEvent.click(await screen.findByTestId("copy-timecode"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("00:01:12–00:01:40"));
    expect(toast.success).toHaveBeenCalledWith("时间码已复制", expect.objectContaining({ toasterId: KB_TOASTER_ID }));
  });

  it("文本 chunk 不渲染视频条（旧渲染零回归）", async () => {
    mockChunks([CHUNK]);
    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);
    expect(await screen.findByText(CHUNK.text)).toBeTruthy();
    expect(screen.queryByTestId("video-shot-bar")).toBeNull();
    expect(screen.queryByTestId("timecode-chip")).toBeNull();
  });
});

// ── 内嵌播放器（spec 2026-09-08 §5，plan Task 10b）──────────────────────
// 抽屉顶部单例 <video>（原生 controls、preload=metadata、不自动播）；点芯片/缩略图
// → seek(start_ms/1000)+play；timeupdate → currentTime 落某镜头 [start,end) 则该行
// 高亮（不抢滚动）；引用闪环定位 → 载到 start_ms 但保持暂停。
// HTMLMediaElement spy：jsdom 的 play() 未实现、currentTime 不回写，故在原型上
// 装可观察的 setter/play 替身（render 前装，捕获 focus effect 的同步 seek）。
function installMediaSpy() {
  let value = 0;
  const setSpy = rs.fn();
  const playSpy = rs.fn().mockResolvedValue(undefined);
  const proto = HTMLMediaElement.prototype;
  const origTime = Object.getOwnPropertyDescriptor(proto, "currentTime");
  const origPlay = Object.getOwnPropertyDescriptor(proto, "play");
  Object.defineProperty(proto, "currentTime", {
    configurable: true,
    get: () => value,
    set: (v: number) => {
      value = v;
      setSpy(v);
    },
  });
  Object.defineProperty(proto, "play", { configurable: true, writable: true, value: playSpy });
  return {
    setSpy,
    playSpy,
    setTime: (v: number) => {
      value = v;
    },
    restore: () => {
      if (origTime) Object.defineProperty(proto, "currentTime", origTime);
      if (origPlay) Object.defineProperty(proto, "play", origPlay);
    },
  };
}

describe("ChunkDrawer 内嵌播放器（spec 2026-09-08 §5）", () => {
  let restoreMedia: (() => void) | null = null;
  afterEach(() => {
    restoreMedia?.();
    restoreMedia = null;
  });

  const SHOT1: KnowledgeChunk = {
    ...VIDEO_CHUNK,
    chunk_id: "doc-1#0001",
    chunk_index: 1,
    shot_index: 1,
    start_ms: 100_000, // 00:01:40
    end_ms: 140_000, // 00:02:20
    frame_url: "/api/knowledge-bases/kb-1/documents/doc-1/shots/1/frame",
  };

  it("视频文档在抽屉顶部渲染单例 <video>（原生 controls、preload=metadata、不自播、src 指向 stream）", async () => {
    mockChunks([VIDEO_CHUNK, SHOT1]);
    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);
    const video = await screen.findByTestId("shot-player");
    expect(video.hasAttribute("controls")).toBe(true);
    expect(video.getAttribute("preload")).toBe("metadata");
    expect(video.hasAttribute("autoplay")).toBe(false);
    expect(video.getAttribute("src")).toContain("documents/doc-1/video/stream");
  });

  it("点时间码芯片 → 播放器 seek 到 start_ms/1000 并 play()", async () => {
    const spy = installMediaSpy();
    restoreMedia = spy.restore;
    mockChunks([VIDEO_CHUNK, SHOT1]);
    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);
    await screen.findByTestId("shot-player");
    const chips = screen.getAllByTestId("timecode-chip");
    fireEvent.click(chips[1]!); // shot 1
    expect(spy.setSpy).toHaveBeenCalledWith(100); // 100000/1000
    expect(spy.playSpy).toHaveBeenCalled();
  });

  it("timeupdate → currentTime 落某镜头 [start,end) 时该行高亮", async () => {
    const spy = installMediaSpy();
    restoreMedia = spy.restore;
    mockChunks([VIDEO_CHUNK, SHOT1]);
    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);
    const video = await screen.findByTestId("shot-player");
    spy.setTime(105); // 落 shot1 [100,140)
    fireEvent(video, new Event("timeupdate"));
    await waitFor(() =>
      expect(document.querySelector('[data-chunk-id="doc-1#0001"]')?.getAttribute("data-shot-active")).toBe("true"),
    );
    expect(document.querySelector('[data-chunk-id="doc-1#0000"]')?.getAttribute("data-shot-active")).toBeNull();
  });

  it("引用定位（focusChunkId）→ 播放器载到该镜头 start_ms 但保持暂停（不 play）", async () => {
    const spy = installMediaSpy();
    restoreMedia = spy.restore;
    mockChunks([VIDEO_CHUNK, SHOT1]);
    renderWithI18n(
      <ChunkDrawer kbId="kb-1" doc={DOC} open focusChunkId="doc-1#0001" onOpenChange={() => undefined} />,
    );
    await screen.findByTestId("shot-player");
    await waitFor(() => expect(spy.setSpy).toHaveBeenCalledWith(100));
    expect(spy.playSpy).not.toHaveBeenCalled();
  });

  it("纯文本文档不渲染播放器", async () => {
    mockChunks([CHUNK]);
    renderWithI18n(<ChunkDrawer kbId="kb-1" doc={DOC} open onOpenChange={() => undefined} />);
    expect(await screen.findByText(CHUNK.text)).toBeTruthy();
    expect(screen.queryByTestId("shot-player")).toBeNull();
  });
});
