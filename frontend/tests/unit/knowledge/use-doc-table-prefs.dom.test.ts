/**
 * 文档表格列偏好的本地持久化 hook（2026-09-02，方案 Task 1）：列显隐 +
 * 时间格式（绝对/相对）+ 大小单位（KB/MB），per-kb 独立存储。
 * 仿 kb-order.dom.test.ts 的模式（renderHook + act + window.localStorage
 * 预置/断言 + 脏数据存活 + 类型守卫）。
 */
import { afterEach, describe, expect, it } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

import {
  DEFAULT_DOC_TABLE_PREFS,
  DOC_TABLE_PREFS_KEY_PREFIX,
  readDocTablePrefs,
  useDocTablePrefs,
  writeDocTablePrefs,
} from "@/core/knowledge/use-doc-table-prefs";

function key(kbId: string): string {
  return `${DOC_TABLE_PREFS_KEY_PREFIX}${kbId}.v1`;
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("useDocTablePrefs", () => {
  it("无存储时回退默认偏好（全显 / 绝对时间 / KB）", () => {
    const { result } = renderHook(() => useDocTablePrefs("kb-1"));
    expect(DEFAULT_DOC_TABLE_PREFS).toEqual({
      hidden: [],
      timeFormat: "absolute",
      sizeUnit: "kb",
    });
    expect(result.current.prefs).toEqual(DEFAULT_DOC_TABLE_PREFS);
  });

  it("toggleColumn 隐藏再显示，且变更写回 localStorage", () => {
    const { result } = renderHook(() => useDocTablePrefs("kb-1"));
    act(() => result.current.toggleColumn("uploader"));
    expect(result.current.prefs.hidden).toEqual(["uploader"]);
    expect(
      JSON.parse(window.localStorage.getItem(key("kb-1"))!).hidden,
    ).toEqual(["uploader"]);
    act(() => result.current.toggleColumn("uploader"));
    expect(result.current.prefs.hidden).toEqual([]);
  });

  it("setTimeFormat / setSizeUnit 切换并持久化", () => {
    const { result } = renderHook(() => useDocTablePrefs("kb-1"));
    act(() => result.current.setTimeFormat("relative"));
    act(() => result.current.setSizeUnit("mb"));
    expect(result.current.prefs.timeFormat).toBe("relative");
    expect(result.current.prefs.sizeUnit).toBe("mb");
    const stored = JSON.parse(window.localStorage.getItem(key("kb-1"))!);
    expect(stored.timeFormat).toBe("relative");
    expect(stored.sizeUnit).toBe("mb");
  });

  it("resetColumns 清空隐藏列", () => {
    const { result } = renderHook(() => useDocTablePrefs("kb-1"));
    act(() => {
      result.current.toggleColumn("size");
      result.current.toggleColumn("chunks");
    });
    expect(result.current.prefs.hidden).toEqual(["size", "chunks"]);
    act(() => result.current.resetColumns());
    expect(result.current.prefs.hidden).toEqual([]);
  });

  it("应用已存偏好", () => {
    window.localStorage.setItem(
      key("kb-1"),
      JSON.stringify({
        hidden: ["createdAt"],
        timeFormat: "relative",
        sizeUnit: "mb",
      }),
    );
    const { result } = renderHook(() => useDocTablePrefs("kb-1"));
    expect(result.current.prefs).toEqual({
      hidden: ["createdAt"],
      timeFormat: "relative",
      sizeUnit: "mb",
    });
  });

  it("per-kb 隔离：切换 kbId 重读该库偏好", () => {
    writeDocTablePrefs("kb-2", {
      hidden: ["chunks"],
      timeFormat: "relative",
      sizeUnit: "mb",
    });
    const { result, rerender } = renderHook(({ id }) => useDocTablePrefs(id), {
      initialProps: { id: "kb-1" },
    });
    expect(result.current.prefs.hidden).toEqual([]);
    rerender({ id: "kb-2" });
    expect(result.current.prefs.hidden).toEqual(["chunks"]);
    expect(result.current.prefs.sizeUnit).toBe("mb");
  });

  it("切换 kbId 后写回落到新库，不污染旧库", () => {
    const { result, rerender } = renderHook(({ id }) => useDocTablePrefs(id), {
      initialProps: { id: "kb-1" },
    });
    rerender({ id: "kb-2" });
    act(() => result.current.toggleColumn("size"));
    expect(
      JSON.parse(window.localStorage.getItem(key("kb-2"))!).hidden,
    ).toEqual(["size"]);
    // kb-1 未被写入 size 隐藏（写回用最新 kbId，无 race 污染）。
    expect(readDocTablePrefs("kb-1").hidden).toEqual([]);
  });

  it("脏数据存活：非法 JSON 回退默认", () => {
    window.localStorage.setItem(key("kb-1"), "not-json");
    const { result } = renderHook(() => useDocTablePrefs("kb-1"));
    expect(result.current.prefs).toEqual(DEFAULT_DOC_TABLE_PREFS);
  });

  it("类型守卫：非法列 id / 非法枚举被过滤回退", () => {
    window.localStorage.setItem(
      key("kb-1"),
      JSON.stringify({
        hidden: ["name", "status", "uploader", "bogus"],
        timeFormat: "weird",
        sizeUnit: "gb",
      }),
    );
    const { result } = renderHook(() => useDocTablePrefs("kb-1"));
    // name 不可隐藏、bogus 非法 → 都滤掉；status 自 2026-09-03 起可隐藏，
    // 与 uploader 一并保留（filter 保序，不重排）。
    expect(result.current.prefs.hidden).toEqual(["status", "uploader"]);
    expect(result.current.prefs.timeFormat).toBe("absolute");
    expect(result.current.prefs.sizeUnit).toBe("kb");
  });
});
