import { expect, rs, test } from "@rstest/core";

import type {
  PersistedUserSettings,
  PersistedUserSettingsPatch,
} from "@/core/settings/persistence";
import {
  UserSettingsSyncController,
  type UserSettingsSyncStore,
  type UserSettingsTransport,
} from "@/core/settings/sync";

function settings(modelName = "local-model"): PersistedUserSettings {
  return {
    notification: { enabled: true },
    tokenUsage: { headerTotal: true, inlineMode: "per_turn" },
    context: {
      model_name: modelName,
      mode: "thinking",
      reasoning_effort: "medium",
    },
  };
}

class FakeStore implements UserSettingsSyncStore {
  current: PersistedUserSettings;
  version = 0;
  pendingPatch: PersistedUserSettingsPatch | null = null;
  hydrateCalls: PersistedUserSettings[] = [];
  private listeners = new Set<(patch: PersistedUserSettingsPatch) => void>();

  constructor(initial: PersistedUserSettings) {
    this.current = structuredClone(initial);
  }

  getSettings = () => structuredClone(this.current);
  getMutationVersion = () => this.version;
  getPendingPatch = () => structuredClone(this.pendingPatch);
  setPendingPatch = (patch: PersistedUserSettingsPatch | null) => {
    this.pendingPatch = structuredClone(patch);
  };

  hydrate = (next: PersistedUserSettings, expectedVersion: number) => {
    if (expectedVersion !== this.version) return false;
    this.current = structuredClone(next);
    this.hydrateCalls.push(structuredClone(next));
    return true;
  };

  subscribeMutations = (
    listener: (patch: PersistedUserSettingsPatch) => void,
  ) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  mutate(patch: PersistedUserSettingsPatch) {
    this.version += 1;
    if (patch.context?.model_name !== undefined) {
      this.current.context.model_name = patch.context.model_name ?? undefined;
    }
    if (patch.tokenUsage?.inlineMode !== undefined) {
      this.current.tokenUsage.inlineMode = patch.tokenUsage.inlineMode;
    }
    for (const listener of this.listeners) listener(patch);
  }
}

function transportWithServer(
  initial: PersistedUserSettings | null,
): UserSettingsTransport & {
  initialize: ReturnType<typeof rs.fn>;
  patch: ReturnType<typeof rs.fn>;
} {
  let server = initial === null ? null : structuredClone(initial);
  return {
    get: rs.fn(async () => ({ settings: server, revision: server ? 1 : 0 })),
    initialize: rs.fn(async (local: PersistedUserSettings) => {
      server ??= structuredClone(local);
      return { settings: structuredClone(server), revision: 1 };
    }),
    patch: rs.fn(async (patch: PersistedUserSettingsPatch) => {
      if (!server) throw new Error("server was not initialized");
      if (patch.context?.model_name !== undefined) {
        server.context.model_name = patch.context.model_name ?? undefined;
      }
      if (patch.tokenUsage?.inlineMode !== undefined) {
        server.tokenUsage.inlineMode = patch.tokenUsage.inlineMode;
      }
      return { settings: structuredClone(server), revision: 2 };
    }),
  };
}

test("hydrates an authenticated user's existing server settings", async () => {
  const store = new FakeStore(settings("stale-local"));
  const transport = transportWithServer(settings("server-model"));
  const controller = new UserSettingsSyncController(store, transport);

  await controller.start();

  expect(store.current.context.model_name).toBe("server-model");
  expect(transport.initialize).not.toHaveBeenCalled();
  expect(transport.patch).not.toHaveBeenCalled();
  controller.stop();
});

test("migrates valid local base settings only when the server record is absent", async () => {
  const local = settings("local-only");
  const store = new FakeStore(local);
  const transport = transportWithServer(null);
  const controller = new UserSettingsSyncController(store, transport);

  await controller.start();

  expect(transport.initialize).toHaveBeenCalledTimes(1);
  expect(transport.initialize).toHaveBeenCalledWith(local);
  expect(transport.patch).not.toHaveBeenCalled();
  controller.stop();
});

test("keeps local fallback when hydration fails or the gateway is offline", async () => {
  const local = settings("offline-local");
  const store = new FakeStore(local);
  const transport: UserSettingsTransport = {
    get: rs.fn(async () => {
      throw new Error("offline");
    }),
    initialize: rs.fn(),
    patch: rs.fn(),
  };
  const controller = new UserSettingsSyncController(store, transport);

  await expect(controller.start()).resolves.toBeUndefined();

  expect(store.current).toEqual(local);
  expect(store.hydrateCalls).toHaveLength(0);
  controller.stop();
});

test("replays a newer local mutation instead of applying a stale hydrate response", async () => {
  let resolveGet!: (value: {
    settings: PersistedUserSettings;
    revision: number;
  }) => void;
  const getPromise = new Promise<{
    settings: PersistedUserSettings;
    revision: number;
  }>((resolve) => {
    resolveGet = resolve;
  });
  const store = new FakeStore(settings("local-before-load"));
  const transport = transportWithServer(settings("server-before-load"));
  transport.get = rs.fn(() => getPromise);
  const controller = new UserSettingsSyncController(store, transport);

  const starting = controller.start();
  store.mutate({ context: { model_name: "new-local-model" } });
  resolveGet({ settings: settings("server-before-load"), revision: 1 });
  await starting;
  await controller.whenIdle();

  expect(store.current.context.model_name).toBe("new-local-model");
  expect(transport.patch).toHaveBeenCalledWith({
    context: { model_name: "new-local-model" },
  });
  controller.stop();
});

test("does not let an older PATCH response roll back a newer local edit", async () => {
  let resolveFirstPatch!: (value: {
    settings: PersistedUserSettings;
    revision: number;
  }) => void;
  const firstPatch = new Promise<{
    settings: PersistedUserSettings;
    revision: number;
  }>((resolve) => {
    resolveFirstPatch = resolve;
  });
  const store = new FakeStore(settings("initial"));
  const transport = transportWithServer(settings("server"));
  let patchCount = 0;
  transport.patch = rs.fn(async () => {
    patchCount += 1;
    if (patchCount === 1) return firstPatch;
    return { settings: settings("newest"), revision: 3 };
  });
  const controller = new UserSettingsSyncController(store, transport);
  await controller.start();

  store.mutate({ context: { model_name: "older-edit" } });
  store.mutate({ context: { model_name: "newest" } });
  resolveFirstPatch({ settings: settings("older-edit"), revision: 2 });
  await controller.whenIdle();

  expect(store.current.context.model_name).toBe("newest");
  expect(transport.patch).toHaveBeenCalledTimes(2);
  expect(transport.patch).toHaveBeenNthCalledWith(2, {
    context: { model_name: "newest" },
  });
  controller.stop();
});

test("keeps the local edit when a background PATCH fails", async () => {
  const store = new FakeStore(settings("initial"));
  const transport = transportWithServer(settings("server"));
  transport.patch = rs.fn(async () => {
    throw new Error("offline during write");
  });
  const controller = new UserSettingsSyncController(store, transport);
  await controller.start();

  store.mutate({ context: { model_name: "offline-edit" } });
  await controller.whenIdle();

  expect(store.current.context.model_name).toBe("offline-edit");
  expect(transport.patch).toHaveBeenCalledTimes(1);
  expect(store.pendingPatch).toEqual({
    context: { model_name: "offline-edit" },
  });
  controller.stop();
});

test("persists an in-flight write before a reload can interrupt it", async () => {
  const store = new FakeStore(settings("initial"));
  let resolvePatch!: (value: {
    settings: PersistedUserSettings;
    revision: number;
  }) => void;
  const pendingRequest = new Promise<{
    settings: PersistedUserSettings;
    revision: number;
  }>((resolve) => {
    resolvePatch = resolve;
  });
  const transport = transportWithServer(settings("server"));
  transport.patch = rs.fn(() => pendingRequest);
  const controller = new UserSettingsSyncController(store, transport);
  await controller.start();

  store.mutate({ context: { model_name: "survives-reload" } });
  await Promise.resolve();

  expect(store.pendingPatch).toEqual({
    context: { model_name: "survives-reload" },
  });
  controller.stop();
  resolvePatch({ settings: settings("survives-reload"), revision: 2 });
  await controller.whenIdle();
});

test("replays a failed write before a later GET can overwrite the local choice", async () => {
  const firstStore = new FakeStore(settings("initial"));
  const failingTransport = transportWithServer(settings("server-old"));
  failingTransport.patch = rs.fn(async () => {
    throw new Error("offline during write");
  });
  const first = new UserSettingsSyncController(firstStore, failingTransport);
  await first.start();
  firstStore.mutate({ context: { model_name: "unsynced-local" } });
  await first.whenIdle();
  first.stop();

  const reloadedStore = new FakeStore(settings("unsynced-local"));
  reloadedStore.pendingPatch = structuredClone(firstStore.pendingPatch);
  const recoveredTransport = transportWithServer(settings("server-old"));
  const reloaded = new UserSettingsSyncController(
    reloadedStore,
    recoveredTransport,
  );
  await reloaded.start();
  await reloaded.whenIdle();

  expect(reloadedStore.current.context.model_name).toBe("unsynced-local");
  expect(recoveredTransport.patch).toHaveBeenCalledWith({
    context: { model_name: "unsynced-local" },
  });
  expect(reloadedStore.pendingPatch).toBeNull();
  reloaded.stop();
});

test("a reload hydrates the value migrated by the previous session", async () => {
  const transport = transportWithServer(null);
  const firstStore = new FakeStore(settings("migrated-model"));
  const first = new UserSettingsSyncController(firstStore, transport);
  await first.start();
  first.stop();

  const reloadedStore = new FakeStore(settings("different-local"));
  const reloaded = new UserSettingsSyncController(reloadedStore, transport);
  await reloaded.start();

  expect(reloadedStore.current.context.model_name).toBe("migrated-model");
  expect(transport.initialize).toHaveBeenCalledTimes(1);
  reloaded.stop();
});
