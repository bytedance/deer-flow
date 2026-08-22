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
  getPersistedBaseSettingsSnapshot,
  getPendingBaseSettingsPatch,
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
  expect(getPendingBaseSettingsPatch("user-a")).toEqual({
    tokenUsage: { headerTotal: true, inlineMode: "off" },
  });
  releaseLock?.();

  await waitFor(() =>
    expect(mockedPatchUserSettings).toHaveBeenCalledWith("user-a", {
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "off" },
      context: {
        model_name: null,
        mode: null,
        reasoning_effort: null,
      },
    }),
  );
  expect(mockedInitializeUserSettings).not.toHaveBeenCalled();
  expect(getPersistedBaseSettingsSnapshot().tokenUsage.inlineMode).toBe("off");
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
      notification: { enabled: true },
      tokenUsage: { headerTotal: true, inlineMode: "off" },
      context: {
        model_name: null,
        mode: null,
        reasoning_effort: null,
      },
    }),
  );
  expect(getPersistedBaseSettingsSnapshot().tokenUsage.inlineMode).toBe("off");
});

test("a cancelled activation cannot seed another account's snapshot", async () => {
  let releaseLock: (() => void) | undefined;
  let lockRequested = false;
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: (_name: string, _options: object, callback: () => unknown) => {
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
    tokenUsage: { headerTotal: true, inlineMode: "off" },
  });
});

test("a prior account mutation before activation does not dirty the next account", async () => {
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
    tokenUsage: { headerTotal: true, inlineMode: "off" },
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

  savePendingBaseSettingsPatch("user-a", null);
  expect(getPendingBaseSettingsPatch("user-a")).toBeNull();
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
  expect(listener).toHaveBeenCalledWith({
    notification: { enabled: true },
    tokenUsage: { headerTotal: true, inlineMode: "step_debug" },
    context: {
      model_name: null,
      mode: null,
      reasoning_effort: null,
    },
  });
  unsubscribe();
  deactivate();
});
