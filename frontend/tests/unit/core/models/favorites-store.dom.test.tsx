import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  rs,
} from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { favoritesKey, serializeFavoriteNames } from "@/core/models/favorites";
import type * as FavoritesStoreModule from "@/core/models/favorites-store";
import type * as FavoritesHookModule from "@/core/models/use-model-favorites";

let store: typeof FavoritesStoreModule;
let hooks: typeof FavoritesHookModule;

function dispatchStorage(
  key: string | null,
  {
    newValue = null,
    storageArea = window.localStorage,
  }: { newValue?: string | null; storageArea?: Storage | null } = {},
) {
  const event = new Event("storage");
  Object.defineProperties(event, {
    key: { value: key },
    newValue: { value: newValue },
    storageArea: { value: storageArea },
  });
  window.dispatchEvent(event);
}

beforeEach(async () => {
  cleanup();
  rs.restoreAllMocks();
  window.localStorage.clear();
  window.sessionStorage.clear();
  rs.resetModules();
  store = await import("@/core/models/favorites-store");
  hooks = await import("@/core/models/use-model-favorites");
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("model favorites snapshots", () => {
  test("keeps a stable empty snapshot for signed-out users without storage access", () => {
    const getItem = rs.spyOn(window.localStorage, "getItem");
    const setItem = rs.spyOn(window.localStorage, "setItem");

    const first = store.getFavoritesSnapshot(null);
    const second = store.getFavoritesSnapshot(null);
    store.setModelFavorite(null, "openai/gpt-5", true);

    expect(first).toBe(store.EMPTY_FAVORITES);
    expect(second).toBe(first);
    expect(first).toEqual({ names: [], persistence: "memory" });
    expect(getItem).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
  });

  test("lazily loads each user and retains the snapshot reference until data changes", () => {
    window.localStorage.setItem(
      favoritesKey("alice"),
      serializeFavoriteNames(["openai/gpt-5"]),
    );
    const getItem = rs.spyOn(window.localStorage, "getItem");

    const first = store.getFavoritesSnapshot("alice");
    const second = store.getFavoritesSnapshot("alice");

    expect(first).toEqual({
      names: ["openai/gpt-5"],
      persistence: "local",
    });
    expect(second).toBe(first);
    expect(getItem).toHaveBeenCalledTimes(1);
  });

  test("treats malformed persisted JSON as an empty local snapshot", () => {
    window.localStorage.setItem(favoritesKey("alice"), "not-json");

    expect(store.getFavoritesSnapshot("alice")).toEqual({
      names: [],
      persistence: "local",
    });

    store.setModelFavorite("alice", "openai/gpt-5", true);
    expect(window.localStorage.getItem(favoritesKey("alice"))).toBe(
      serializeFavoriteNames(["openai/gpt-5"]),
    );
  });

  test("distinguishes an initial read exception from a genuinely missing value", () => {
    const getItem = rs
      .spyOn(window.localStorage, "getItem")
      .mockImplementation(() => {
        throw new DOMException("blocked", "SecurityError");
      });

    expect(store.getFavoritesSnapshot("alice")).toEqual({
      names: [],
      persistence: "local",
    });

    getItem.mockRestore();
    const setItem = rs.spyOn(window.localStorage, "setItem");
    store.setModelFavorite("alice", "openai/gpt-5", true);

    expect(setItem).toHaveBeenCalledWith(
      favoritesKey("alice"),
      serializeFavoriteNames(["openai/gpt-5"]),
    );
    expect(store.getFavoritesSnapshot("alice").persistence).toBe("local");
  });

  test("does not write or notify for idempotent updates", () => {
    const listener = rs.fn();
    const unsubscribe = store.subscribeFavorites("alice", listener);
    const setItem = rs.spyOn(window.localStorage, "setItem");
    const initial = store.getFavoritesSnapshot("alice");

    store.setModelFavorite("alice", "openai/gpt-5", false);
    store.setModelFavorite("alice", "   ", true);

    expect(store.getFavoritesSnapshot("alice")).toBe(initial);
    expect(setItem).not.toHaveBeenCalled();
    expect(listener).not.toHaveBeenCalled();
    unsubscribe();
  });

  test("uses the latest in-memory value for consecutive changes", () => {
    store.setModelFavorite("alice", "openai/gpt-5", true);
    store.setModelFavorite("alice", "anthropic/claude", true);
    store.setModelFavorite("alice", "openai/gpt-5", false);

    expect(store.getFavoritesSnapshot("alice").names).toEqual([
      "anthropic/claude",
    ]);
    expect(window.localStorage.getItem(favoritesKey("alice"))).toBe(
      serializeFavoriteNames(["anthropic/claude"]),
    );
  });
});

describe("useModelFavorites", () => {
  test("synchronizes two mounted hooks immediately", () => {
    const first = renderHook(() => hooks.useModelFavorites("alice"));
    const second = renderHook(() => hooks.useModelFavorites("alice"));

    act(() => first.result.current.setFavorite("openai/gpt-5", true));

    expect(first.result.current.names).toEqual(["openai/gpt-5"]);
    expect(second.result.current.names).toEqual(["openai/gpt-5"]);
    expect(first.result.current.persistence).toBe("local");
    expect(first.result.current.canEdit).toBe(true);
  });

  test("switches A to signed-out to B without flashing A and disables edits", () => {
    window.localStorage.setItem(
      favoritesKey("alice"),
      serializeFavoriteNames(["alice/model"]),
    );
    window.localStorage.setItem(
      favoritesKey("bob"),
      serializeFavoriteNames(["bob/model"]),
    );
    const { result, rerender } = renderHook(
      ({ userId }: { userId: string | null }) =>
        hooks.useModelFavorites(userId),
      { initialProps: { userId: "alice" as string | null } },
    );

    expect(result.current.names).toEqual(["alice/model"]);
    rerender({ userId: null });
    expect(result.current.names).toEqual([]);
    expect(result.current.canEdit).toBe(false);

    const setItem = rs.spyOn(window.localStorage, "setItem");
    setItem.mockClear();
    act(() => result.current.setFavorite("ignored/model", true));
    expect(setItem).not.toHaveBeenCalled();
    expect(result.current.names).toEqual([]);

    rerender({ userId: "bob" });
    expect(result.current.names).toEqual(["bob/model"]);
  });

  test("uses the fixed empty server snapshot during SSR", () => {
    window.localStorage.setItem(
      favoritesKey("alice"),
      serializeFavoriteNames(["browser/model"]),
    );

    function Probe() {
      const favorites = hooks.useModelFavorites("alice");
      return createElement("span", null, favorites.names.join(","));
    }

    expect(() => renderToStaticMarkup(createElement(Probe))).not.toThrow();
    expect(renderToStaticMarkup(createElement(Probe))).toBe("<span></span>");
  });
});

describe("failed persistence", () => {
  test("sticks to memory after a failed write and ignores later external events", () => {
    const setItem = rs
      .spyOn(window.localStorage, "setItem")
      .mockImplementation(() => {
        throw new DOMException("quota", "QuotaExceededError");
      });
    const { result } = renderHook(() => hooks.useModelFavorites("alice"));

    act(() => result.current.setFavorite("openai/gpt-5", true));
    expect(result.current).toMatchObject({
      names: ["openai/gpt-5"],
      persistence: "memory",
      canEdit: true,
    });
    expect(setItem).toHaveBeenCalledTimes(1);

    act(() => result.current.setFavorite("anthropic/claude", true));
    expect(result.current.names).toEqual(["openai/gpt-5", "anthropic/claude"]);
    expect(setItem).toHaveBeenCalledTimes(1);

    setItem.mockRestore();
    window.localStorage.setItem(
      favoritesKey("alice"),
      serializeFavoriteNames(["external/model"]),
    );
    act(() => dispatchStorage(favoritesKey("alice")));
    expect(result.current.names).toEqual(["openai/gpt-5", "anthropic/claude"]);
  });
});

describe("storage event synchronization", () => {
  test("reloads the current local value for its user and ignores another user", () => {
    const { result } = renderHook(() => hooks.useModelFavorites("alice"));

    window.localStorage.setItem(
      favoritesKey("bob"),
      serializeFavoriteNames(["bob/model"]),
    );
    act(() => dispatchStorage(favoritesKey("bob")));
    expect(result.current.names).toEqual([]);

    window.localStorage.setItem(
      favoritesKey("alice"),
      serializeFavoriteNames(["alice/model"]),
    );
    act(() => dispatchStorage(favoritesKey("alice")));
    expect(result.current.names).toEqual(["alice/model"]);
  });

  test("uses current storage instead of delayed event.newValue", () => {
    const { result } = renderHook(() => hooks.useModelFavorites("alice"));
    window.localStorage.setItem(
      favoritesKey("alice"),
      serializeFavoriteNames(["current/model"]),
    );

    act(() =>
      dispatchStorage(favoritesKey("alice"), {
        newValue: serializeFavoriteNames(["stale/model"]),
      }),
    );

    expect(result.current.names).toEqual(["current/model"]);
  });

  test("accepts a real deletion and clear for all cached local users", () => {
    window.localStorage.setItem(
      favoritesKey("alice"),
      serializeFavoriteNames(["alice/model"]),
    );
    window.localStorage.setItem(
      favoritesKey("bob"),
      serializeFavoriteNames(["bob/model"]),
    );
    const alice = renderHook(() => hooks.useModelFavorites("alice"));
    const bob = renderHook(() => hooks.useModelFavorites("bob"));

    window.localStorage.removeItem(favoritesKey("alice"));
    act(() => dispatchStorage(favoritesKey("alice")));
    expect(alice.result.current.names).toEqual([]);
    expect(bob.result.current.names).toEqual(["bob/model"]);

    window.localStorage.clear();
    act(() => dispatchStorage(null));
    expect(alice.result.current.names).toEqual([]);
    expect(bob.result.current.names).toEqual([]);
  });

  test("ignores sessionStorage and a throwing storageArea getter", () => {
    const { result } = renderHook(() => hooks.useModelFavorites("alice"));
    window.localStorage.setItem(
      favoritesKey("alice"),
      serializeFavoriteNames(["external/model"]),
    );

    act(() =>
      dispatchStorage(favoritesKey("alice"), {
        storageArea: window.sessionStorage,
      }),
    );
    expect(result.current.names).toEqual([]);

    const event = new Event("storage");
    Object.defineProperties(event, {
      key: { value: favoritesKey("alice") },
      storageArea: {
        get() {
          throw new DOMException("blocked", "SecurityError");
        },
      },
    });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(result.current.names).toEqual([]);
  });

  test("preserves the snapshot when an event-triggered read throws", () => {
    window.localStorage.setItem(
      favoritesKey("alice"),
      serializeFavoriteNames(["initial/model"]),
    );
    const { result } = renderHook(() => hooks.useModelFavorites("alice"));
    rs.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    act(() => dispatchStorage(favoritesKey("alice")));

    expect(result.current.names).toEqual(["initial/model"]);
  });

  test("recalibrates a local entry when it is subscribed again", () => {
    const first = renderHook(() => hooks.useModelFavorites("alice"));
    expect(first.result.current.names).toEqual([]);
    first.unmount();

    window.localStorage.setItem(
      favoritesKey("alice"),
      serializeFavoriteNames(["while-unsubscribed/model"]),
    );
    const second = renderHook(() => hooks.useModelFavorites("alice"));

    expect(second.result.current.names).toEqual(["while-unsubscribed/model"]);
  });

  test("registers the window listener only for non-null subscribers and cleans it up", () => {
    const add = rs.spyOn(window, "addEventListener");
    const remove = rs.spyOn(window, "removeEventListener");
    const signedOut = renderHook(() => hooks.useModelFavorites(null));
    expect(add.mock.calls.filter(([type]) => type === "storage")).toHaveLength(
      0,
    );

    const alice = renderHook(() => hooks.useModelFavorites("alice"));
    const bob = renderHook(() => hooks.useModelFavorites("bob"));
    expect(add.mock.calls.filter(([type]) => type === "storage")).toHaveLength(
      1,
    );

    alice.unmount();
    expect(
      remove.mock.calls.filter(([type]) => type === "storage"),
    ).toHaveLength(0);
    bob.unmount();
    expect(
      remove.mock.calls.filter(([type]) => type === "storage"),
    ).toHaveLength(1);
    signedOut.unmount();
  });
});
