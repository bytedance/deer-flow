/**
 * 用户自建抽屉的本地持久化（2026-09-04）：命名 + 图标/配色的分组，对「我的条目」
 * 内的卡片做分区（每卡 ≤1 抽屉；无/失效归属 = 未分组）。仿 kb-order.dom.test.ts /
 * use-doc-table-prefs.dom.test.ts 的模式（renderHook + act + window.localStorage
 * 预置/断言 + 脏数据存活 + 类型守卫 + per-kb 隔离）。
 */
import { afterEach, describe, expect, it } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

import {
  DRAWER_DEFAULT_COLOR,
  DRAWER_DEFAULT_ICON,
  cardDrawersKey,
  readCardDrawers,
  useCardDrawers,
  writeCardDrawers,
} from "@/core/knowledge/card-drawers";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("useCardDrawers", () => {
  it("无存储时回退空态（无抽屉 / 无归属）", () => {
    const { result } = renderHook(() => useCardDrawers("kb-1"));
    expect(result.current.drawers).toEqual([]);
    expect(result.current.membership).toEqual({});
    expect(result.current.drawerOf("card-1")).toBeUndefined();
  });

  it("createDrawer 追加抽屉、返回 id、trim 名称并写回 localStorage", () => {
    const { result } = renderHook(() => useCardDrawers("kb-1"));
    let id = "";
    act(() => {
      id = result.current.createDrawer({
        name: "  运维手册  ",
        icon: "folder",
        color: "emerald",
      });
    });
    expect(id).not.toBe("");
    expect(result.current.drawers).toEqual([
      { id, name: "运维手册", icon: "folder", color: "emerald" },
    ]);
    const stored = JSON.parse(
      window.localStorage.getItem(cardDrawersKey("kb-1"))!,
    );
    expect(stored.drawers).toHaveLength(1);
    expect(stored.drawers[0].name).toBe("运维手册");
  });

  it("moveCard 建立归属、drawerOf 反映；移出（null）归为未分组", () => {
    const { result } = renderHook(() => useCardDrawers("kb-1"));
    let id = "";
    act(() => {
      id = result.current.createDrawer({
        name: "运维",
        icon: "folder",
        color: "teal",
      });
    });
    act(() => result.current.moveCard("card-1", id));
    expect(result.current.drawerOf("card-1")).toBe(id);
    expect(
      JSON.parse(window.localStorage.getItem(cardDrawersKey("kb-1"))!)
        .membership,
    ).toEqual({ "card-1": id });
    act(() => result.current.moveCard("card-1", null));
    expect(result.current.drawerOf("card-1")).toBeUndefined();
    expect(
      JSON.parse(window.localStorage.getItem(cardDrawersKey("kb-1"))!)
        .membership,
    ).toEqual({});
  });

  it("moveCards 批量移动：单次 persist 写入全部选中卡归属（避免逐张 stale-state 覆盖）", () => {
    const { result } = renderHook(() => useCardDrawers("kb-1"));
    let b = "";
    act(() => {
      result.current.createDrawer({
        name: "A",
        icon: "folder",
        color: "emerald",
      });
    });
    act(() => {
      b = result.current.createDrawer({
        name: "B",
        icon: "star",
        color: "blue",
      });
    });
    // 一次把 3 张卡归入 B：全部写入（若逐张 moveCard 会因 stale state 只留最后一张）。
    act(() => result.current.moveCards(["card-1", "card-2", "card-3"], b));
    expect(result.current.drawerOf("card-1")).toBe(b);
    expect(result.current.drawerOf("card-2")).toBe(b);
    expect(result.current.drawerOf("card-3")).toBe(b);
    expect(
      JSON.parse(window.localStorage.getItem(cardDrawersKey("kb-1"))!)
        .membership,
    ).toEqual({ "card-1": b, "card-2": b, "card-3": b });
    // 批量移回未分组（null）：一次清空全部归属。
    act(() => result.current.moveCards(["card-1", "card-2", "card-3"], null));
    expect(result.current.drawerOf("card-1")).toBeUndefined();
    expect(
      JSON.parse(window.localStorage.getItem(cardDrawersKey("kb-1"))!)
        .membership,
    ).toEqual({});
  });

  it("updateDrawer 改名/改图标/改色并持久化（未提供的字段保留）", () => {
    const { result } = renderHook(() => useCardDrawers("kb-1"));
    let id = "";
    act(() => {
      id = result.current.createDrawer({
        name: "旧名",
        icon: "folder",
        color: "emerald",
      });
    });
    act(() => result.current.updateDrawer(id, { name: "新名", color: "rose" }));
    expect(result.current.drawers[0]).toEqual({
      id,
      name: "新名",
      icon: "folder", // 未改，保留
      color: "rose",
    });
    const stored = JSON.parse(
      window.localStorage.getItem(cardDrawersKey("kb-1"))!,
    );
    expect(stored.drawers[0].name).toBe("新名");
    expect(stored.drawers[0].color).toBe("rose");
  });

  it("deleteDrawer 删抽屉并清除指向它的归属（卡片不删，回未分组）", () => {
    const { result } = renderHook(() => useCardDrawers("kb-1"));
    let a = "";
    let b = "";
    act(() => {
      a = result.current.createDrawer({
        name: "A",
        icon: "folder",
        color: "emerald",
      });
    });
    act(() => {
      b = result.current.createDrawer({
        name: "B",
        icon: "star",
        color: "blue",
      });
    });
    act(() => {
      result.current.moveCard("card-1", a);
      result.current.moveCard("card-2", b);
    });
    act(() => result.current.deleteDrawer(a));
    // A 删除：card-1 归属被清（回未分组）；B 与 card-2 不受影响。
    expect(result.current.drawers.map((d) => d.id)).toEqual([b]);
    expect(result.current.drawerOf("card-1")).toBeUndefined();
    expect(result.current.drawerOf("card-2")).toBe(b);
    expect(
      JSON.parse(window.localStorage.getItem(cardDrawersKey("kb-1"))!)
        .membership,
    ).toEqual({ "card-2": b });
  });

  it("setDrawerHidden 收起/展开抽屉（只翻 hidden，抽屉与归属不动，读写保真）", () => {
    const { result } = renderHook(() => useCardDrawers("kb-1"));
    let id = "";
    act(() => {
      id = result.current.createDrawer({
        name: "运维",
        icon: "folder",
        color: "emerald",
      });
    });
    act(() => result.current.moveCard("card-1", id));
    act(() => result.current.setDrawerHidden(id, true));
    // 收起：抽屉仍在、hidden=true、归属不动。
    expect(result.current.drawers).toHaveLength(1);
    expect(result.current.drawers[0]?.hidden).toBe(true);
    expect(result.current.drawerOf("card-1")).toBe(id);
    expect(
      JSON.parse(window.localStorage.getItem(cardDrawersKey("kb-1"))!)
        .drawers[0].hidden,
    ).toBe(true);
    // 展开：hidden 翻回 false；读写往返后 sanitize 不写 hidden 键（= 显示）。
    act(() => result.current.setDrawerHidden(id, false));
    expect(result.current.drawers[0]?.hidden).toBe(false);
    expect(readCardDrawers("kb-1").drawers[0]?.hidden).toBeFalsy();
  });

  it("revealDrawerToFront 取消收起并移到最前（-> 下拉点击语义，读写保真）", () => {
    const { result } = renderHook(() => useCardDrawers("kb-1"));
    let a = "";
    let b = "";
    act(() => {
      a = result.current.createDrawer({
        name: "A",
        icon: "folder",
        color: "emerald",
      });
    });
    act(() => {
      b = result.current.createDrawer({
        name: "B",
        icon: "star",
        color: "blue",
      });
    });
    act(() => result.current.moveCard("card-1", b));
    // 收起第二个抽屉 B（顺序 [A, B]，B hidden）。
    act(() => result.current.setDrawerHidden(b, true));
    expect(result.current.drawers.map((d) => d.id)).toEqual([a, b]);
    expect(result.current.drawers[1]?.hidden).toBe(true);
    // 下拉点击 B：取消收起 + 移到最前 → [B, A]，归属不动，B 无 hidden 键。
    act(() => result.current.revealDrawerToFront(b));
    expect(result.current.drawers.map((d) => d.id)).toEqual([b, a]);
    expect(result.current.drawers[0]?.hidden).toBeFalsy();
    expect(result.current.drawerOf("card-1")).toBe(b);
    // 持久化：读写往返后顺序 [B, A]，首个抽屉无 hidden 键（sanitize 保真）。
    const stored = readCardDrawers("kb-1");
    expect(stored.drawers.map((d) => d.id)).toEqual([b, a]);
    expect(stored.drawers[0]?.hidden).toBeFalsy();
  });

  it("per-kb 隔离：切换 kbId 重读该库抽屉与归属", () => {
    writeCardDrawers("kb-2", {
      drawers: [{ id: "d2", name: "库二抽屉", icon: "flag", color: "amber" }],
      membership: { "card-x": "d2" },
    });
    const { result, rerender } = renderHook(({ id }) => useCardDrawers(id), {
      initialProps: { id: "kb-1" },
    });
    expect(result.current.drawers).toEqual([]);
    rerender({ id: "kb-2" });
    expect(result.current.drawers.map((d) => d.name)).toEqual(["库二抽屉"]);
    expect(result.current.drawerOf("card-x")).toBe("d2");
  });
});

describe("readCardDrawers / writeCardDrawers", () => {
  it("往返读写", () => {
    const state = {
      drawers: [
        {
          id: "d1",
          name: "运维",
          icon: "folder" as const,
          color: "emerald" as const,
        },
      ],
      membership: { "card-1": "d1" },
    };
    writeCardDrawers("kb-1", state);
    expect(readCardDrawers("kb-1")).toEqual(state);
  });

  it("脏数据存活：非法 JSON 回退空态", () => {
    window.localStorage.setItem(cardDrawersKey("kb-1"), "not-json");
    expect(readCardDrawers("kb-1")).toEqual({ drawers: [], membership: {} });
  });

  it("类型守卫：非法 icon/color 回退默认，缺 id/name 的抽屉项与非字符串归属被丢弃", () => {
    window.localStorage.setItem(
      cardDrawersKey("kb-1"),
      JSON.stringify({
        drawers: [
          { id: "ok", name: "合法", icon: "bogus-icon", color: "bogus-color" },
          { id: "no-name", icon: "folder", color: "emerald" }, // 缺 name → 丢弃
          { name: "no-id", icon: "folder", color: "emerald" }, // 缺 id → 丢弃
        ],
        membership: { "card-1": "ok", "card-2": 42 }, // 非字符串值 → 丢弃
      }),
    );
    const state = readCardDrawers("kb-1");
    expect(state.drawers).toEqual([
      {
        id: "ok",
        name: "合法",
        icon: DRAWER_DEFAULT_ICON,
        color: DRAWER_DEFAULT_COLOR,
      },
    ]);
    expect(state.membership).toEqual({ "card-1": "ok" });
  });
});
