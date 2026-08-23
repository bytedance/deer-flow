import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, render, waitFor } from "@testing-library/react";

rs.mock("@/core/settings/api", () => ({
  fetchUserSettings: rs.fn(),
  initializeUserSettings: rs.fn(),
  patchUserSettings: rs.fn(),
}));

import {
  fetchUserSettings,
  initializeUserSettings,
  patchUserSettings,
} from "@/core/settings/api";
import {
  activateBaseSettingsPersistence,
  getOutstandingBaseSettingsVolatileLeaves,
  getPersistedBaseSettingsSnapshot,
  getPendingBaseSettingsPatch,
  getPendingBaseSettingsPatchBatch,
  savePendingBaseSettingsPatch,
  subscribeBaseSettingsMutations,
  updateLocalSettings,
} from "@/core/settings/store";
import { UserSettingsSync } from "@/core/settings/user-settings-sync";

const mockedFetchUserSettings = rs.mocked(fetchUserSettings);
const mockedInitializeUserSettings = rs.mocked(initializeUserSettings);
const mockedPatchUserSettings = rs.mocked(patchUserSettings);

afterEach(() => {
  cleanup();
  localStorage.clear();
  mockedFetchUserSettings.mockReset();
  mockedInitializeUserSettings.mockReset();
  mockedPatchUserSettings.mockReset();
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: undefined,
  });
  rs.restoreAllMocks();
});

function installSerialWebLocks() {
  let tail: Promise<unknown> = Promise.resolve();
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (
        _name: string,
        optionsOrCallback: object | (() => unknown),
        maybeCallback?: () => unknown,
      ) => {
        const callback: () => unknown =
          typeof optionsOrCallback === "function"
            ? (optionsOrCallback as () => unknown)
            : maybeCallback!;
        const result = tail.then(callback);
        tail = result.then(
          () => undefined,
          () => undefined,
        );
        return result;
      },
    },
  });
}

test("auth-disabled mode leaves the existing local-only behavior untouched", async () => {
  render(<UserSettingsSync enabled={false} userId="default" />);
  await Promise.resolve();

  expect(mockedFetchUserSettings).not.toHaveBeenCalled();
});

test("an edit made while legacy activation waits is outboxed before server hydration", async () => {
  let releaseLock: (() => void) | undefined;
  let lockRequested = false;
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (_name: string, _options: object, callback: () => unknown) => {
        if (_name !== "deerflow.user-settings-legacy-migration") {
          return Promise.resolve(callback());
        }
        lockRequested = true;
        return new Promise<unknown>((resolve) => {
          releaseLock = () => resolve(callback());
        });
      },
    },
  });
  mockedFetchUserSettings.mockResolvedValue({
    settings: {
      notification: { enabled: false },
      tokenUsage: { headerTotal: false, inlineMode: "per_turn" },
      context: { model_name: "server-model" },
    },
    revision: 1,
  });
  mockedPatchUserSettings.mockResolvedValue({
    settings: {
      notification: { enabled: false },
      tokenUsage: { headerTotal: false, inlineMode: "off" },
      context: { model_name: "server-model" },
    },
    revision: 2,
  });

  render(<UserSettingsSync enabled userId="user-a" />);
  await waitFor(() => expect(lockRequested).toBe(true));

  updateLocalSettings("tokenUsage", { inlineMode: "off" });
  expect(getPendingBaseSettingsPatch("user-a")).toEqual({
    tokenUsage: { inlineMode: "off" },
  });
  releaseLock?.();

  await waitFor(() =>
    expect(mockedPatchUserSettings).toHaveBeenCalledWith("user-a", {
      tokenUsage: { inlineMode: "off" },
    }),
  );
  expect(mockedInitializeUserSettings).not.toHaveBeenCalled();
  expect(getPersistedBaseSettingsSnapshot()).toEqual({
    notification: { enabled: false },
    tokenUsage: { headerTotal: false, inlineMode: "off" },
    context: { model_name: "server-model" },
  });
});

test("an activation-gap cache hydration is not replayed as a local mutation", async () => {
  const before = getPersistedBaseSettingsSnapshot();
  let releaseLock: (() => void) | undefined;
  let lockRequested = false;
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (_name: string, _options: object, callback: () => unknown) => {
        if (_name !== "deerflow.user-settings-legacy-migration") {
          return Promise.resolve(callback());
        }
        lockRequested = true;
        return new Promise<unknown>((resolve) => {
          releaseLock = () => resolve(callback());
        });
      },
    },
  });
  const hydratedCache = {
    ...before,
    context: { ...before.context, model_name: "other-tab-hydration" },
  };
  const newerServer = {
    ...before,
    context: { ...before.context, model_name: "newer-server" },
  };
  mockedFetchUserSettings.mockResolvedValue({
    settings: newerServer,
    revision: 4,
  });
  mockedPatchUserSettings.mockResolvedValue({
    settings: newerServer,
    revision: 5,
  });

  render(<UserSettingsSync enabled userId="user-a" />);
  await waitFor(() => expect(lockRequested).toBe(true));
  localStorage.setItem(
    "deerflow.user-settings-cache.user-a",
    JSON.stringify(hydratedCache),
  );
  window.dispatchEvent(
    new StorageEvent("storage", {
      key: "deerflow.user-settings-cache.user-a",
      storageArea: localStorage,
    }),
  );
  releaseLock?.();

  await waitFor(() =>
    expect(mockedFetchUserSettings).toHaveBeenCalledWith("user-a"),
  );
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(mockedPatchUserSettings).not.toHaveBeenCalled();
  expect(getPersistedBaseSettingsSnapshot().context.model_name).toBe(
    "newer-server",
  );
});

test("an activation-gap edit survives when browser storage rejects outbox writes", async () => {
  updateLocalSettings("tokenUsage", { inlineMode: "per_turn" });
  rs.spyOn(localStorage, "setItem").mockImplementation(() => {
    throw new DOMException("Blocked", "SecurityError");
  });
  let releaseLock: (() => void) | undefined;
  let lockRequested = false;
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (_name: string, _options: object, callback: () => unknown) => {
        if (_name !== "deerflow.user-settings-legacy-migration") {
          return Promise.resolve(callback());
        }
        lockRequested = true;
        return new Promise<unknown>((resolve) => {
          releaseLock = () => resolve(callback());
        });
      },
    },
  });
  mockedFetchUserSettings.mockResolvedValue({
    settings: {
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
      context: {},
    },
    revision: 1,
  });
  mockedPatchUserSettings.mockResolvedValue({
    settings: {
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "off" },
      context: {},
    },
    revision: 2,
  });

  render(<UserSettingsSync enabled userId="user-a" />);
  await waitFor(() => expect(lockRequested).toBe(true));
  updateLocalSettings("tokenUsage", { inlineMode: "off" });
  expect(getPendingBaseSettingsPatch("user-a")).toBeNull();
  releaseLock?.();

  await waitFor(() =>
    expect(mockedPatchUserSettings).toHaveBeenCalledWith("user-a", {
      tokenUsage: { inlineMode: "off" },
    }),
  );
  expect(getPersistedBaseSettingsSnapshot().tokenUsage.inlineMode).toBe("off");
});

test("a volatile pre-bootstrap edit survives an account switch and remount", async () => {
  for (const userId of ["user-a", "user-b"]) {
    localStorage.setItem(
      `deerflow.user-settings-cache.${userId}`,
      JSON.stringify({
        notification: { enabled: true },
        tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
        context: {},
      }),
    );
  }
  const originalSetItem = localStorage.setItem.bind(localStorage);
  rs.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
    if (key.startsWith("deerflow.user-settings-pending.leaf.")) {
      throw new DOMException("Blocked", "SecurityError");
    }
    originalSetItem(key, value);
  });
  let releaseBootstrapLock: (() => void) | undefined;
  let bootstrapLockRequested = false;
  let shouldBlockAlice = true;
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (_name: string, _options: object, callback: () => unknown) => {
        if (shouldBlockAlice && _name.endsWith(".user-a")) {
          shouldBlockAlice = false;
          bootstrapLockRequested = true;
          return new Promise<unknown>((resolve) => {
            releaseBootstrapLock = () => resolve(callback());
          });
        }
        return Promise.resolve(callback());
      },
    },
  });
  mockedFetchUserSettings.mockImplementation(async (userId) => ({
    settings: {
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
      context: userId === "user-a" ? {} : { model_name: "bob-model" },
    },
    revision: 1,
  }));
  mockedPatchUserSettings.mockResolvedValue({
    settings: {
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
      context: { model_name: "alice-volatile" },
    },
    revision: 2,
  });

  const view = render(<UserSettingsSync enabled userId="user-a" />);
  await waitFor(() => expect(bootstrapLockRequested).toBe(true));
  updateLocalSettings("context", { model_name: "alice-volatile" });
  expect(getPendingBaseSettingsPatch("user-a")).toBeNull();
  expect(getOutstandingBaseSettingsVolatileLeaves("user-a")).toHaveLength(1);

  view.rerender(<UserSettingsSync enabled userId="user-b" />);
  releaseBootstrapLock?.();
  await waitFor(() =>
    expect(mockedFetchUserSettings).toHaveBeenCalledWith("user-b"),
  );
  expect(getOutstandingBaseSettingsVolatileLeaves("user-a")).toHaveLength(1);
  view.rerender(<UserSettingsSync enabled userId="user-a" />);

  await waitFor(() =>
    expect(mockedFetchUserSettings).toHaveBeenCalledWith("user-a"),
  );
  await waitFor(() =>
    expect(mockedPatchUserSettings).toHaveBeenCalledWith("user-a", {
      context: { model_name: "alice-volatile" },
    }),
  );
});

test("a failed volatile write is retried after the sync controller remounts", async () => {
  installSerialWebLocks();
  localStorage.setItem(
    "deerflow.user-settings-cache.user-a",
    JSON.stringify({
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
      context: {},
    }),
  );
  const originalSetItem = localStorage.setItem.bind(localStorage);
  rs.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
    if (key.startsWith("deerflow.user-settings-pending.leaf.")) {
      throw new DOMException("Blocked", "SecurityError");
    }
    originalSetItem(key, value);
  });
  mockedFetchUserSettings.mockResolvedValue({
    settings: {
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
      context: {},
    },
    revision: 1,
  });
  mockedPatchUserSettings
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue({
      settings: {
        notification: { enabled: true },
        tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
        context: { model_name: "retry-after-remount" },
      },
      revision: 2,
    });

  const firstView = render(<UserSettingsSync enabled userId="user-a" />);
  await waitFor(() =>
    expect(mockedFetchUserSettings).toHaveBeenCalledWith("user-a"),
  );
  updateLocalSettings("context", { model_name: "retry-after-remount" });
  await waitFor(() => expect(mockedPatchUserSettings).toHaveBeenCalledTimes(1));
  firstView.unmount();

  const secondView = render(<UserSettingsSync enabled userId="user-a" />);

  await waitFor(() => expect(mockedPatchUserSettings).toHaveBeenCalledTimes(2));
  expect(mockedPatchUserSettings).toHaveBeenLastCalledWith("user-a", {
    context: { model_name: "retry-after-remount" },
  });

  secondView.unmount();
  render(<UserSettingsSync enabled userId="user-a" />);
  await waitFor(() => expect(mockedFetchUserSettings).toHaveBeenCalledTimes(3));
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(mockedPatchUserSettings).toHaveBeenCalledTimes(2);
});

test("activation seeding cannot overwrite a later durable leaf hidden behind a storage event", async () => {
  updateLocalSettings("tokenUsage", { inlineMode: "per_turn" });
  savePendingBaseSettingsPatch("user-a", {
    tokenUsage: { inlineMode: "per_turn" },
  });
  let releaseLock: (() => void) | undefined;
  let lockRequested = false;
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (_name: string, _options: object, callback: () => unknown) => {
        if (_name !== "deerflow.user-settings-legacy-migration") {
          return Promise.resolve(callback());
        }
        lockRequested = true;
        return new Promise<unknown>((resolve) => {
          releaseLock = () => resolve(callback());
        });
      },
    },
  });
  mockedFetchUserSettings.mockResolvedValue({
    settings: {
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
      context: {},
    },
    revision: 1,
  });
  mockedPatchUserSettings.mockResolvedValue({
    settings: {
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "step_debug" },
      context: {},
    },
    revision: 2,
  });

  render(<UserSettingsSync enabled userId="user-a" />);
  await waitFor(() => expect(lockRequested).toBe(true));
  savePendingBaseSettingsPatch("user-a", {
    tokenUsage: { inlineMode: "off" },
  });
  localStorage.setItem(
    "deerflow.user-settings-cache.user-a",
    JSON.stringify({
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "off" },
      context: {},
    }),
  );
  window.dispatchEvent(
    new StorageEvent("storage", {
      key: "deerflow.user-settings-cache.user-a",
      storageArea: localStorage,
    }),
  );
  savePendingBaseSettingsPatch("user-a", {
    tokenUsage: { inlineMode: "step_debug" },
  });
  releaseLock?.();

  await waitFor(() =>
    expect(mockedPatchUserSettings).toHaveBeenCalledWith("user-a", {
      tokenUsage: { inlineMode: "step_debug" },
    }),
  );
  expect(mockedPatchUserSettings).not.toHaveBeenCalledWith("user-a", {
    tokenUsage: { inlineMode: "off" },
  });
});

test("a cancelled activation cannot seed another account's snapshot", async () => {
  updateLocalSettings("tokenUsage", { inlineMode: "per_turn" });
  let releaseLock: (() => void) | undefined;
  let lockRequested = false;
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (_name: string, _options: object, callback: () => unknown) => {
        if (_name !== "deerflow.user-settings-legacy-migration") {
          return Promise.resolve(callback());
        }
        lockRequested = true;
        return new Promise<unknown>((resolve) => {
          releaseLock = () => resolve(callback());
        });
      },
    },
  });
  localStorage.setItem(
    "deerflow.user-settings-cache.user-b",
    JSON.stringify({
      notification: { enabled: false },
      tokenUsage: { headerTotal: false, inlineMode: "step_debug" },
      context: { model_name: "bob-model" },
    }),
  );
  mockedFetchUserSettings.mockResolvedValue({
    settings: {
      notification: { enabled: false },
      tokenUsage: { headerTotal: false, inlineMode: "step_debug" },
      context: { model_name: "bob-model" },
    },
    revision: 1,
  });

  const view = render(<UserSettingsSync enabled userId="user-a" />);
  await waitFor(() => expect(lockRequested).toBe(true));
  updateLocalSettings("tokenUsage", { inlineMode: "off" });
  view.rerender(<UserSettingsSync enabled userId="user-b" />);
  await waitFor(() =>
    expect(mockedFetchUserSettings).toHaveBeenCalledWith("user-b"),
  );

  releaseLock?.();
  await new Promise((resolve) => setTimeout(resolve, 0));

  expect(getPendingBaseSettingsPatch("user-a")).toEqual({
    tokenUsage: { inlineMode: "off" },
  });
});

test("a prior account mutation before activation does not dirty the next account", async () => {
  installSerialWebLocks();
  localStorage.setItem(
    "deerflow.user-settings-cache.user-a",
    JSON.stringify({
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
      context: {},
    }),
  );
  localStorage.setItem(
    "deerflow.user-settings-cache.user-b",
    JSON.stringify({
      notification: { enabled: false },
      tokenUsage: { headerTotal: false, inlineMode: "step_debug" },
      context: { model_name: "bob-model" },
    }),
  );
  const deactivateAlice = await activateBaseSettingsPersistence("user-a");
  mockedFetchUserSettings.mockResolvedValue({
    settings: {
      notification: { enabled: false },
      tokenUsage: { headerTotal: false, inlineMode: "step_debug" },
      context: { model_name: "bob-model" },
    },
    revision: 1,
  });

  function AliceMutationDuringRender() {
    updateLocalSettings("tokenUsage", { inlineMode: "off" });
    return null;
  }

  render(
    <>
      <UserSettingsSync enabled userId="user-b" />
      <AliceMutationDuringRender />
    </>,
  );
  await waitFor(() =>
    expect(mockedFetchUserSettings).toHaveBeenCalledWith("user-b"),
  );

  expect(mockedPatchUserSettings).not.toHaveBeenCalled();
  expect(getPendingBaseSettingsPatch("user-a")).toEqual({
    tokenUsage: { inlineMode: "off" },
  });
  expect(getPendingBaseSettingsPatch("user-b")).toBeNull();
  deactivateAlice();
});

test("failed-write outboxes are isolated by authenticated user", () => {
  savePendingBaseSettingsPatch("user-a", {
    context: { model_name: "unsynced-model" },
  });

  expect(getPendingBaseSettingsPatch("user-a")).toEqual({
    context: { model_name: "unsynced-model" },
  });
  expect(getPendingBaseSettingsPatch("user-b")).toBeNull();
  expect(getPendingBaseSettingsPatch("user-a.ack")).toBeNull();

  savePendingBaseSettingsPatch("user-a", null);
  expect(getPendingBaseSettingsPatch("user-a")).toBeNull();
});

test("legacy monolithic outboxes remain readable and clearable", () => {
  const legacyKey = "deerflow.user-settings-pending.user-a";
  localStorage.setItem(
    legacyKey,
    JSON.stringify({ context: { model_name: "legacy-pending" } }),
  );

  const batch = getPendingBaseSettingsPatchBatch("user-a");
  expect(batch?.patch).toEqual({
    context: { model_name: "legacy-pending" },
  });
  expect(batch?.acknowledge()).toBe(true);
  expect(getPendingBaseSettingsPatch("user-a")).toBeNull();

  savePendingBaseSettingsPatch("user-a", null);
  expect(localStorage.getItem(legacyKey)).toBeNull();
});

test("a legacy unscoped cache is claimed by only one authenticated user", async () => {
  installSerialWebLocks();
  localStorage.setItem(
    "deerflow.local-settings",
    JSON.stringify({
      notification: { enabled: false },
      tokenUsage: { headerTotal: false, inlineMode: "off" },
      context: { model_name: "alice-model", mode: "thinking" },
    }),
  );

  const deactivateAlice = await activateBaseSettingsPersistence("user-a");
  expect(getPersistedBaseSettingsSnapshot().context.model_name).toBe(
    "alice-model",
  );
  deactivateAlice();

  const deactivateBob = await activateBaseSettingsPersistence("user-b");
  expect(getPersistedBaseSettingsSnapshot()).toEqual({
    notification: { enabled: true },
    tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
    context: {},
  });
  deactivateBob();
});

test("concurrent account activation imports the legacy cache at most once", async () => {
  installSerialWebLocks();
  localStorage.setItem(
    "deerflow.local-settings",
    JSON.stringify({
      notification: { enabled: false },
      tokenUsage: { headerTotal: false, inlineMode: "off" },
      context: { model_name: "legacy-model" },
    }),
  );

  const [deactivateAlice, deactivateBob] = await Promise.all([
    activateBaseSettingsPersistence("user-a"),
    activateBaseSettingsPersistence("user-b"),
  ]);
  const alice = JSON.parse(
    localStorage.getItem("deerflow.user-settings-cache.user-a") ?? "null",
  ) as { context?: { model_name?: string } } | null;
  const bob = JSON.parse(
    localStorage.getItem("deerflow.user-settings-cache.user-b") ?? "null",
  ) as { context?: { model_name?: string } } | null;

  expect(
    [alice, bob].filter(
      (settings) => settings?.context?.model_name === "legacy-model",
    ),
  ).toHaveLength(1);
  expect(localStorage.getItem("deerflow.local-settings-owner")).toBe("user-a");
  deactivateAlice();
  deactivateBob();
});

test("without Web Locks an unowned legacy cache is not imported", async () => {
  localStorage.setItem(
    "deerflow.local-settings",
    JSON.stringify({
      notification: { enabled: false },
      tokenUsage: { headerTotal: false, inlineMode: "off" },
      context: { model_name: "ambiguous-owner" },
    }),
  );

  const deactivate = await activateBaseSettingsPersistence("user-a");

  expect(getPersistedBaseSettingsSnapshot().context.model_name).toBeUndefined();
  expect(localStorage.getItem("deerflow.local-settings-owner")).toBeNull();
  deactivate();
});

test("another account's tab cache cannot replace the active user's fallback", async () => {
  const deactivate = await activateBaseSettingsPersistence("user-b");
  const before = getPersistedBaseSettingsSnapshot();

  window.dispatchEvent(
    new StorageEvent("storage", {
      key: "deerflow.user-settings-cache.user-a",
      newValue: JSON.stringify({
        notification: { enabled: false },
        tokenUsage: { headerTotal: false, inlineMode: "off" },
        context: { model_name: "alice-model" },
      }),
      storageArea: localStorage,
    }),
  );

  expect(getPersistedBaseSettingsSnapshot()).toEqual(before);
  deactivate();
});

test("the same account's tab cache still produces a synchronized mutation", async () => {
  const deactivate = await activateBaseSettingsPersistence("user-a");
  const listener = rs.fn();
  const unsubscribe = subscribeBaseSettingsMutations(listener);

  localStorage.setItem(
    "deerflow.user-settings-cache.user-a",
    JSON.stringify({
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "step_debug" },
      context: {},
    }),
  );
  window.dispatchEvent(
    new StorageEvent("storage", {
      key: "deerflow.user-settings-cache.user-a",
      storageArea: localStorage,
    }),
  );

  expect(getPersistedBaseSettingsSnapshot().tokenUsage.inlineMode).toBe(
    "step_debug",
  );
  expect(listener).toHaveBeenCalledWith(
    {
      tokenUsage: { inlineMode: "step_debug" },
    },
    {
      durableLeaves: [],
      volatileLeaves: [],
    },
  );
  unsubscribe();
  deactivate();
});

test("a local leaf edit preserves a newer sibling leaf from another tab", async () => {
  const deactivate = await activateBaseSettingsPersistence("user-a");
  const listener = rs.fn();
  const unsubscribe = subscribeBaseSettingsMutations(listener);
  localStorage.setItem(
    "deerflow.user-settings-cache.user-a",
    JSON.stringify({
      notification: { enabled: true },
      tokenUsage: { headerTotal: false, inlineMode: "per_turn" },
      context: {},
    }),
  );

  updateLocalSettings("tokenUsage", { inlineMode: "off" });

  expect(
    JSON.parse(
      localStorage.getItem("deerflow.user-settings-cache.user-a") ?? "null",
    ),
  ).toEqual({
    notification: { enabled: true },
    tokenUsage: { headerTotal: false, inlineMode: "off" },
    context: {},
  });
  expect(listener).toHaveBeenCalledWith(
    {
      tokenUsage: { inlineMode: "off" },
    },
    {
      durableLeaves: ["tokenUsage.inlineMode"],
      volatileLeaves: [],
    },
  );
  unsubscribe();
  deactivate();
});

test("a stale same-value edit is diffed against the latest shared cache", async () => {
  localStorage.setItem(
    "deerflow.user-settings-cache.user-a",
    JSON.stringify({
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
      context: {},
    }),
  );
  const deactivate = await activateBaseSettingsPersistence("user-a");
  const listener = rs.fn();
  const unsubscribe = subscribeBaseSettingsMutations(listener);
  localStorage.setItem(
    "deerflow.user-settings-cache.user-a",
    JSON.stringify({
      notification: { enabled: false },
      tokenUsage: { headerTotal: false, inlineMode: "off" },
      context: { model_name: "newer-sibling" },
    }),
  );

  updateLocalSettings("tokenUsage", { inlineMode: "per_turn" });

  expect(
    JSON.parse(
      localStorage.getItem("deerflow.user-settings-cache.user-a") ?? "null",
    ),
  ).toEqual({
    notification: { enabled: false },
    tokenUsage: { headerTotal: false, inlineMode: "per_turn" },
    context: { model_name: "newer-sibling" },
  });
  expect(listener).toHaveBeenCalledWith(
    { tokenUsage: { inlineMode: "per_turn" } },
    {
      durableLeaves: ["tokenUsage.inlineMode"],
      volatileLeaves: [],
    },
  );
  unsubscribe();
  deactivate();
});

test("consecutive volatile leaf edits preserve earlier in-memory values", async () => {
  localStorage.setItem(
    "deerflow.user-settings-cache.storage-blocked-user",
    JSON.stringify({
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
      context: {},
    }),
  );
  const deactivate = await activateBaseSettingsPersistence(
    "storage-blocked-user",
  );
  rs.spyOn(localStorage, "setItem").mockImplementation(() => {
    throw new DOMException("Blocked", "SecurityError");
  });

  updateLocalSettings("tokenUsage", { inlineMode: "off" });
  updateLocalSettings("notification", { enabled: false });

  expect(getPersistedBaseSettingsSnapshot()).toEqual({
    notification: { enabled: false },
    tokenUsage: { headerTotal: true, inlineMode: "off" },
    context: {},
  });
  deactivate();
});

test("an acknowledged edit remains in the baseline when only its cache write fails", async () => {
  installSerialWebLocks();
  const cacheKey = "deerflow.user-settings-cache.cache-failure-user";
  const initialSettings = {
    notification: { enabled: true },
    tokenUsage: { headerTotal: true, inlineMode: "per_turn" as const },
    context: {},
  };
  localStorage.setItem(cacheKey, JSON.stringify(initialSettings));
  mockedFetchUserSettings.mockResolvedValue({
    settings: initialSettings,
    revision: 1,
  });
  mockedPatchUserSettings.mockResolvedValue({
    settings: initialSettings,
    revision: 2,
  });

  render(<UserSettingsSync enabled userId="cache-failure-user" />);
  await waitFor(() =>
    expect(mockedFetchUserSettings).toHaveBeenCalledWith("cache-failure-user"),
  );
  await waitFor(() =>
    expect(getPersistedBaseSettingsSnapshot()).toEqual(initialSettings),
  );

  const originalSetItem = Storage.prototype.setItem.bind(localStorage);
  const newerCrossTabSettings = {
    notification: { enabled: true },
    tokenUsage: { headerTotal: false, inlineMode: "per_turn" },
    context: { model_name: "newer-cross-tab-sibling" },
  };
  let crossTabWriteInjected = false;
  let cacheWriteFailures = 1;
  rs.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
    if (
      key.startsWith("deerflow.user-settings-pending.leaf.") &&
      !crossTabWriteInjected
    ) {
      crossTabWriteInjected = true;
      originalSetItem(cacheKey, JSON.stringify(newerCrossTabSettings));
    }
    if (key === cacheKey && cacheWriteFailures > 0) {
      cacheWriteFailures -= 1;
      throw new DOMException("Blocked", "QuotaExceededError");
    }
    originalSetItem(key, value);
  });

  updateLocalSettings("tokenUsage", { inlineMode: "off" });
  await waitFor(() =>
    expect(mockedPatchUserSettings).toHaveBeenCalledWith("cache-failure-user", {
      tokenUsage: { inlineMode: "off" },
    }),
  );
  await waitFor(() =>
    expect(getPendingBaseSettingsPatch("cache-failure-user")).toBeNull(),
  );
  expect(JSON.parse(localStorage.getItem(cacheKey) ?? "null")).toEqual(
    newerCrossTabSettings,
  );

  updateLocalSettings("notification", { enabled: false });

  await waitFor(() => expect(mockedPatchUserSettings).toHaveBeenCalledTimes(2));
  expect(mockedPatchUserSettings).toHaveBeenLastCalledWith(
    "cache-failure-user",
    { notification: { enabled: false } },
  );
  const expectedSettings = {
    notification: { enabled: false },
    tokenUsage: { headerTotal: false, inlineMode: "off" },
    context: { model_name: "newer-cross-tab-sibling" },
  };
  expect(getPersistedBaseSettingsSnapshot()).toEqual(expectedSettings);
  expect(JSON.parse(localStorage.getItem(cacheKey) ?? "null")).toEqual(
    expectedSettings,
  );
});

test("a successful cache write rebases its leaf over a newer cross-tab sibling", async () => {
  installSerialWebLocks();
  const userId = "cache-rebase-user";
  const cacheKey = `deerflow.user-settings-cache.${userId}`;
  const initialSettings = {
    notification: { enabled: true },
    tokenUsage: { headerTotal: true, inlineMode: "per_turn" as const },
    context: {},
  };
  const newerCrossTabSettings = {
    notification: { enabled: true },
    tokenUsage: { headerTotal: false, inlineMode: "per_turn" as const },
    context: { model_name: "newer-cross-tab-sibling" },
  };
  localStorage.setItem(cacheKey, JSON.stringify(initialSettings));
  mockedFetchUserSettings.mockResolvedValue({
    settings: initialSettings,
    revision: 1,
  });
  mockedPatchUserSettings.mockResolvedValue({
    settings: initialSettings,
    revision: 2,
  });

  render(<UserSettingsSync enabled userId={userId} />);
  await waitFor(() =>
    expect(mockedFetchUserSettings).toHaveBeenCalledWith(userId),
  );
  await waitFor(() =>
    expect(getPersistedBaseSettingsSnapshot()).toEqual(initialSettings),
  );

  const originalSetItem = Storage.prototype.setItem.bind(localStorage);
  let crossTabWriteInjected = false;
  rs.spyOn(localStorage, "setItem").mockImplementation((key, value) => {
    if (
      key.startsWith("deerflow.user-settings-pending.leaf.") &&
      !crossTabWriteInjected
    ) {
      crossTabWriteInjected = true;
      originalSetItem(cacheKey, JSON.stringify(newerCrossTabSettings));
    }
    originalSetItem(key, value);
  });

  updateLocalSettings("tokenUsage", { inlineMode: "off" });

  const firstExpectedSettings = {
    notification: { enabled: true },
    tokenUsage: { headerTotal: false, inlineMode: "off" },
    context: { model_name: "newer-cross-tab-sibling" },
  };
  expect(getPersistedBaseSettingsSnapshot()).toEqual(firstExpectedSettings);
  expect(JSON.parse(localStorage.getItem(cacheKey) ?? "null")).toEqual(
    firstExpectedSettings,
  );
  await waitFor(() =>
    expect(mockedPatchUserSettings).toHaveBeenCalledWith(userId, {
      tokenUsage: { inlineMode: "off" },
    }),
  );
  await waitFor(() => expect(getPendingBaseSettingsPatch(userId)).toBeNull());

  updateLocalSettings("notification", { enabled: false });

  await waitFor(() => expect(mockedPatchUserSettings).toHaveBeenCalledTimes(2));
  expect(mockedPatchUserSettings).toHaveBeenLastCalledWith(userId, {
    notification: { enabled: false },
  });
  const finalExpectedSettings = {
    ...firstExpectedSettings,
    notification: { enabled: false },
  };
  expect(getPersistedBaseSettingsSnapshot()).toEqual(finalExpectedSettings);
  expect(JSON.parse(localStorage.getItem(cacheKey) ?? "null")).toEqual(
    finalExpectedSettings,
  );
});

test("acknowledging one durable batch cannot clear a later tab operation", () => {
  savePendingBaseSettingsPatch("user-a", {
    context: { model_name: "tab-a" },
  });
  const firstBatch = getPendingBaseSettingsPatchBatch("user-a");
  savePendingBaseSettingsPatch("user-a", {
    tokenUsage: { inlineMode: "off" },
  });

  expect(firstBatch?.acknowledge()).toBe(true);
  expect(getPendingBaseSettingsPatch("user-a")).toEqual({
    tokenUsage: { inlineMode: "off" },
  });
});

test("a reload recovers every patch retained by two failed tabs", () => {
  savePendingBaseSettingsPatch("user-a", {
    context: { model_name: "offline-tab-a" },
  });
  savePendingBaseSettingsPatch("user-a", {
    tokenUsage: { inlineMode: "off" },
  });

  expect(getPendingBaseSettingsPatchBatch("user-a")?.patch).toEqual({
    context: { model_name: "offline-tab-a" },
    tokenUsage: { inlineMode: "off" },
  });
});

test("a same-leaf overwrite survives acknowledgement of the older batch", () => {
  rs.spyOn(Date, "now").mockReturnValue(1_700_000_000_000);
  savePendingBaseSettingsPatch("user-a", {
    tokenUsage: { inlineMode: "off" },
  });
  const olderBatch = getPendingBaseSettingsPatchBatch("user-a");
  savePendingBaseSettingsPatch("user-a", {
    tokenUsage: { inlineMode: "step_debug" },
  });

  expect(olderBatch?.acknowledge()).toBe(true);
  expect(getPendingBaseSettingsPatch("user-a")).toEqual({
    tokenUsage: { inlineMode: "step_debug" },
  });
});
