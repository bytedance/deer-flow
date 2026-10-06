/**
 * Local persistence for the kb list: user-defined order (drag reorder) and
 * the remembered last-opened library. Both live in localStorage — the list
 * is per-browser by design here, the backend keeps created_at ordering.
 */
import { afterEach, beforeEach, describe, expect, it } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

import {
  KB_ORDER_STORAGE_KEY,
  LAST_KB_STORAGE_KEY,
  readLastKbId,
  useKbLocalOrder,
  writeLastKbId,
} from "@/core/knowledge/kb-order";
import type { KnowledgeBase } from "@/core/knowledge/types";

function kb(id: string): KnowledgeBase {
  return {
    id,
    owner_id: "u1",
    name: `kb-${id}`,
    description: "",
    visibility: "private",
    created_at: "2026-09-01T00:00:00Z",
  };
}

const THREE = [kb("a"), kb("b"), kb("c")];

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("useKbLocalOrder", () => {
  it("keeps the server order when nothing is stored", () => {
    const { result } = renderHook(() => useKbLocalOrder(THREE));
    expect(result.current.ordered.map((k) => k.id)).toEqual(["a", "b", "c"]);
  });

  it("applies the stored order and appends unknown kbs at the end", () => {
    window.localStorage.setItem(KB_ORDER_STORAGE_KEY, JSON.stringify(["c", "a"]));
    const { result } = renderHook(() => useKbLocalOrder(THREE));
    // c and a follow the stored order; b was never ordered, so it trails.
    expect(result.current.ordered.map((k) => k.id)).toEqual(["c", "a", "b"]);
  });

  it("ignores stored ids that no longer exist", () => {
    window.localStorage.setItem(KB_ORDER_STORAGE_KEY, JSON.stringify(["ghost", "b", "a"]));
    const { result } = renderHook(() => useKbLocalOrder(THREE));
    expect(result.current.ordered.map((k) => k.id)).toEqual(["b", "a", "c"]);
  });

  it("survives garbage in the storage", () => {
    window.localStorage.setItem(KB_ORDER_STORAGE_KEY, "not-json");
    const { result } = renderHook(() => useKbLocalOrder(THREE));
    expect(result.current.ordered.map((k) => k.id)).toEqual(["a", "b", "c"]);
  });

  it("commitMove reorders the list and persists the new order", () => {
    const { result } = renderHook(() => useKbLocalOrder(THREE));
    act(() => {
      // Drag c onto a: c takes a's slot, a and b shift down.
      result.current.commitMove("c", "a");
    });
    expect(result.current.ordered.map((k) => k.id)).toEqual(["c", "a", "b"]);
    expect(JSON.parse(window.localStorage.getItem(KB_ORDER_STORAGE_KEY)!)).toEqual([
      "c",
      "a",
      "b",
    ]);
  });

  it("commitMove is a no-op when the ids match or are unknown", () => {
    const { result } = renderHook(() => useKbLocalOrder(THREE));
    act(() => {
      result.current.commitMove("a", "a");
      result.current.commitMove("a", "ghost");
    });
    expect(result.current.ordered.map((k) => k.id)).toEqual(["a", "b", "c"]);
    expect(window.localStorage.getItem(KB_ORDER_STORAGE_KEY)).toBeNull();
  });
});

describe("remembered last kb", () => {
  it("round-trips the last opened kb id", () => {
    expect(readLastKbId()).toBeNull();
    writeLastKbId("b");
    expect(readLastKbId()).toBe("b");
  });

  it("returns null for non-string garbage", () => {
    window.localStorage.setItem(LAST_KB_STORAGE_KEY, JSON.stringify({ nope: 1 }));
    expect(readLastKbId()).toBeNull();
  });
});
