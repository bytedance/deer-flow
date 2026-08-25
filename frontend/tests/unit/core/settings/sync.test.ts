import { expect, rs, test } from "@rstest/core";

import type {
  PersistedUserSettings,
  PersistedUserSettingsPatch,
} from "@/core/settings/persistence";
import { mergePersistedUserSettingsPatches } from "@/core/settings/persistence";
import {
  UserSettingsSyncController,
  type UserSettingsMutationPersistence,
  type UserSettingsPatchLeaf,
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
  lockAvailable = true;
  hydrateCalls: PersistedUserSettings[] = [];
  private nextOperationId = 0;
  private operations = new Map<number, PersistedUserSettingsPatch>();
  private listeners = new Set<
    (
      patch: PersistedUserSettingsPatch,
      persistence: UserSettingsMutationPersistence,
    ) => void
  >();

  constructor(initial: PersistedUserSettings) {
    this.current = structuredClone(initial);
  }

  getSettings = () => structuredClone(this.current);
  getMutationVersion = () => this.version;
  getPendingPatchBatch = () => {
    const entries = [...this.operations.entries()];
    if (entries.length === 0) return null;
    const patch = entries.reduce<PersistedUserSettingsPatch | null>(
      (merged, [, operation]) =>
        mergePersistedUserSettingsPatches(merged, operation),
      null,
    )!;
    return {
      patch: structuredClone(patch),
      acknowledge: () => {
        for (const [id] of entries) this.operations.delete(id);
        return true;
      },
    };
  };
  getDurableLeafOpId: (leaf: UserSettingsPatchLeaf) => string | null = (
    _leaf,
  ) => null;
  withWriteLock = async (task: () => Promise<void>) => {
    if (!this.lockAvailable) return false;
    await task();
    return true;
  };

  get pendingPatch(): PersistedUserSettingsPatch | null {
    return this.getPendingPatchBatch()?.patch ?? null;
  }

  set pendingPatch(patch: PersistedUserSettingsPatch | null) {
    this.operations.clear();
    if (patch !== null) this.appendPendingPatch(patch);
  }

  hydrate = (next: PersistedUserSettings, expectedVersion: number) => {
    if (expectedVersion !== this.version) return false;
    this.current = structuredClone(next);
    this.hydrateCalls.push(structuredClone(next));
    return true;
  };

  subscribeMutations = (
    listener: (
      patch: PersistedUserSettingsPatch,
      persistence: UserSettingsMutationPersistence,
    ) => void,
  ) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  mutate(patch: PersistedUserSettingsPatch) {
    this.appendPendingPatch(patch);
    const durableLeaves: UserSettingsPatchLeaf[] = [];
    if (patch.context?.model_name !== undefined) {
      durableLeaves.push("context.model_name");
    }
    if (patch.tokenUsage?.inlineMode !== undefined) {
      durableLeaves.push("tokenUsage.inlineMode");
    }
    this.notifyMutation(patch, { durableLeaves, volatileLeaves: [] });
  }

  notifyMutation(
    patch: PersistedUserSettingsPatch,
    persistence: UserSettingsMutationPersistence,
  ) {
    this.version += 1;
    if (patch.context?.model_name !== undefined) {
      this.current.context.model_name = patch.context.model_name ?? undefined;
    }
    if (patch.tokenUsage?.inlineMode !== undefined) {
      this.current.tokenUsage.inlineMode = patch.tokenUsage.inlineMode;
    }
    for (const listener of this.listeners) {
      listener(patch, persistence);
    }
  }

  appendPendingPatch(patch: PersistedUserSettingsPatch) {
    this.operations.set(++this.nextOperationId, structuredClone(patch));
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

test("rereads a later durable leaf after GET even without a storage event", async () => {
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
  const store = new FakeStore(settings("initial"));
  const transport = transportWithServer(settings("server"));
  transport.get = rs.fn(() => getPromise);
  const controller = new UserSettingsSyncController(store, transport);
  const starting = controller.start();

  store.mutate({ context: { model_name: "durable-p" } });
  store.appendPendingPatch({ context: { model_name: "durable-q" } });
  store.current.context.model_name = "durable-q";
  resolveGet({ settings: settings("server"), revision: 1 });
  await starting;
  await controller.whenIdle();

  expect(store.current.context.model_name).toBe("durable-q");
  expect(transport.patch).toHaveBeenCalledWith({
    context: { model_name: "durable-q" },
  });
  controller.stop();
});

test("rejects a stale GET after a newer mutation was already acknowledged", async () => {
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
  const store = new FakeStore(settings("initial"));
  const transport = transportWithServer(settings("old-server"));
  transport.get = rs.fn(() => getPromise);
  const controller = new UserSettingsSyncController(store, transport);
  const starting = controller.start();

  store.mutate({ context: { model_name: "newer-local" } });
  expect(store.getPendingPatchBatch()?.acknowledge()).toBe(true);
  resolveGet({ settings: settings("old-server"), revision: 1 });
  await starting;
  await controller.whenIdle();

  expect(store.current.context.model_name).toBe("newer-local");
  expect(store.hydrateCalls).toHaveLength(0);
  expect(transport.patch).not.toHaveBeenCalled();
  controller.stop();
});

test("holds the write lock while bootstrap folds a preexisting outbox over GET", async () => {
  const store = new FakeStore(settings("pending"));
  store.pendingPatch = { context: { model_name: "pending" } };
  let lockTail = Promise.resolve();
  const withSharedLock = async (task: () => Promise<void>) => {
    const previous = lockTail;
    let release!: () => void;
    lockTail = new Promise<void>((resolve) => {
      release = resolve;
    });
    await previous;
    try {
      await task();
      return true;
    } finally {
      release();
    }
  };
  store.withWriteLock = withSharedLock;
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
  let markGetStarted!: () => void;
  const getStarted = new Promise<void>((resolve) => {
    markGetStarted = resolve;
  });
  const transport = transportWithServer(settings("old-server"));
  transport.get = rs.fn(() => {
    markGetStarted();
    return getPromise;
  });
  const controller = new UserSettingsSyncController(store, transport);
  const starting = controller.start();
  await getStarted;

  let otherTabAcknowledged = false;
  const otherTabWrite = withSharedLock(async () => {
    otherTabAcknowledged = true;
    expect(store.getPendingPatchBatch()?.acknowledge()).toBe(true);
  });
  await Promise.resolve();
  expect(otherTabAcknowledged).toBe(false);

  resolveGet({ settings: settings("old-server"), revision: 1 });
  await Promise.all([starting, otherTabWrite]);
  await controller.whenIdle();

  expect(otherTabAcknowledged).toBe(true);
  expect(store.hydrateCalls).toEqual([settings("pending")]);
  expect(store.current.context.model_name).toBe("pending");
  expect(transport.patch).not.toHaveBeenCalled();
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
  await controller.whenIdle();

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

test("reapplies a pending patch after corrupt-record recovery before acknowledging it", async () => {
  const store = new FakeStore(settings("initial"));
  const transport = transportWithServer(settings("server"));
  let patchAttempt = 0;
  transport.patch = rs.fn(async () => {
    patchAttempt += 1;
    return patchAttempt === 1
      ? { settings: null, revision: 2 }
      : { settings: settings("recovered-edit"), revision: 4 };
  });
  transport.initialize = rs.fn(async () => ({
    // Another device won the first-writer-wins initialization race without
    // this tab's pending mutation.
    settings: settings("other-device"),
    revision: 3,
  }));
  const controller = new UserSettingsSyncController(store, transport);
  await controller.start();

  store.mutate({ context: { model_name: "recovered-edit" } });
  await controller.whenIdle();

  const pendingPatch = {
    context: { model_name: "recovered-edit" },
  };
  expect(transport.patch).toHaveBeenCalledTimes(2);
  expect(transport.patch).toHaveBeenNthCalledWith(1, pendingPatch);
  expect(transport.patch).toHaveBeenNthCalledWith(2, pendingPatch);
  expect(transport.initialize).toHaveBeenCalledWith(
    expect.objectContaining({
      context: expect.objectContaining({ model_name: "recovered-edit" }),
    }),
  );
  expect(store.pendingPatch).toBeNull();
  controller.stop();
});

test("fails closed and retains pending work when the write lock is unavailable", async () => {
  const store = new FakeStore(settings("initial"));
  store.pendingPatch = { context: { model_name: "pending" } };
  store.lockAvailable = false;
  const transport = transportWithServer(settings("server"));
  const controller = new UserSettingsSyncController(store, transport);

  await controller.start();
  await controller.whenIdle();

  expect(transport.patch).not.toHaveBeenCalled();
  expect(store.pendingPatch).toEqual({
    context: { model_name: "pending" },
  });
  controller.stop();
});

test("serializes an older durable write before a later volatile write", async () => {
  const tabA = new FakeStore(settings("initial"));
  const tabB = new FakeStore(settings("initial"));
  let durableSlot: {
    opId: string;
    patch: PersistedUserSettingsPatch;
  } | null = null;
  let acknowledgedOpId: string | null = null;
  let lockTail = Promise.resolve();
  const withSharedLock = async (task: () => Promise<void>) => {
    const previous = lockTail;
    let release!: () => void;
    lockTail = new Promise<void>((resolve) => {
      release = resolve;
    });
    await previous;
    try {
      await task();
      return true;
    } finally {
      release();
    }
  };
  for (const store of [tabA, tabB]) {
    store.getPendingPatchBatch = () => {
      const captured = durableSlot;
      if (captured === null || captured.opId === acknowledgedOpId) return null;
      return {
        patch: structuredClone(captured.patch),
        acknowledge: () => {
          acknowledgedOpId = captured.opId;
          return true;
        },
      };
    };
    store.getDurableLeafOpId = (leaf) =>
      leaf === "context.model_name" ? (durableSlot?.opId ?? null) : null;
    store.withWriteLock = withSharedLock;
  }

  let releaseOlderWrite!: () => void;
  const olderWriteBlocked = new Promise<void>((resolve) => {
    releaseOlderWrite = resolve;
  });
  let markOlderWriteStarted!: () => void;
  const olderWriteStarted = new Promise<void>((resolve) => {
    markOlderWriteStarted = resolve;
  });
  const server = settings("server");
  const patchCalls: PersistedUserSettingsPatch[] = [];
  let inFlight = 0;
  let maximumInFlight = 0;
  const patch = async (nextPatch: PersistedUserSettingsPatch) => {
    patchCalls.push(structuredClone(nextPatch));
    inFlight += 1;
    maximumInFlight = Math.max(maximumInFlight, inFlight);
    try {
      if (nextPatch.context?.model_name === "durable-q") {
        markOlderWriteStarted();
        await olderWriteBlocked;
      }
      if (nextPatch.context?.model_name !== undefined) {
        server.context.model_name = nextPatch.context.model_name ?? undefined;
      }
      return {
        settings: structuredClone(server),
        revision: patchCalls.length + 1,
      };
    } finally {
      inFlight -= 1;
    }
  };
  const transport = (): UserSettingsTransport => ({
    get: async () => ({ settings: structuredClone(server), revision: 1 }),
    initialize: async (local) => ({ settings: local, revision: 1 }),
    patch,
  });
  const controllerA = new UserSettingsSyncController(tabA, transport());
  const controllerB = new UserSettingsSyncController(tabB, transport());
  await Promise.all([controllerA.start(), controllerB.start()]);
  await Promise.all([controllerA.whenIdle(), controllerB.whenIdle()]);

  durableSlot = {
    opId: "q",
    patch: { context: { model_name: "durable-q" } },
  };
  tabA.notifyMutation(durableSlot.patch, {
    durableLeaves: ["context.model_name"],
    volatileLeaves: [],
  });
  await olderWriteStarted;
  tabB.notifyMutation(
    { context: { model_name: "volatile-p" } },
    {
      durableLeaves: [],
      volatileLeaves: [
        {
          leaf: "context.model_name",
          patch: { context: { model_name: "volatile-p" } },
          observedDurableOpId: "q",
        },
      ],
    },
  );
  await Promise.resolve();

  expect(patchCalls).toEqual([{ context: { model_name: "durable-q" } }]);
  expect(maximumInFlight).toBe(1);

  releaseOlderWrite();
  await Promise.all([controllerA.whenIdle(), controllerB.whenIdle()]);

  expect(patchCalls).toEqual([
    { context: { model_name: "durable-q" } },
    { context: { model_name: "volatile-p" } },
  ]);
  expect(maximumInFlight).toBe(1);
  expect(server.context.model_name).toBe("volatile-p");
  controllerA.stop();
  controllerB.stop();
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

test("acknowledging an in-flight batch preserves a patch appended by another tab", async () => {
  let resolveFirstPatch!: (value: {
    settings: PersistedUserSettings;
    revision: number;
  }) => void;
  const firstRequest = new Promise<{
    settings: PersistedUserSettings;
    revision: number;
  }>((resolve) => {
    resolveFirstPatch = resolve;
  });
  const store = new FakeStore(settings("initial"));
  const transport = transportWithServer(settings("server"));
  transport.patch = rs
    .fn()
    .mockImplementationOnce(() => firstRequest)
    .mockResolvedValue({ settings: settings("updated"), revision: 3 });
  const controller = new UserSettingsSyncController(store, transport);
  await controller.start();
  await controller.whenIdle();

  store.mutate({ context: { model_name: "tab-a" } });
  await Promise.resolve();
  store.appendPendingPatch({ context: { model_name: "tab-b-newer" } });
  resolveFirstPatch({ settings: settings("tab-a"), revision: 2 });
  await controller.whenIdle();

  expect(transport.patch).toHaveBeenNthCalledWith(1, {
    context: { model_name: "tab-a" },
  });
  expect(transport.patch).toHaveBeenNthCalledWith(2, {
    context: { model_name: "tab-b-newer" },
  });
  expect(store.pendingPatch).toBeNull();
  controller.stop();
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
