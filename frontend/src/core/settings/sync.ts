import type { UserSettingsResponse } from "./api";
import {
  applyPersistedUserSettingsPatch,
  mergePersistedUserSettingsPatches,
  type PersistedUserSettings,
  type PersistedUserSettingsPatch,
} from "./persistence";

export interface UserSettingsTransport {
  get: () => Promise<UserSettingsResponse>;
  initialize: (
    settings: PersistedUserSettings,
  ) => Promise<UserSettingsResponse>;
  patch: (patch: PersistedUserSettingsPatch) => Promise<UserSettingsResponse>;
}

export type UserSettingsPatchLeaf =
  | "notification.enabled"
  | "tokenUsage.headerTotal"
  | "tokenUsage.inlineMode"
  | "context.model_name"
  | "context.mode"
  | "context.reasoning_effort";

export interface VolatileUserSettingsPatchLeaf {
  version: number;
  leaf: UserSettingsPatchLeaf;
  patch: PersistedUserSettingsPatch;
  observedDurableOpId: string | null;
}

export interface UserSettingsMutationPersistence {
  durableLeaves: UserSettingsPatchLeaf[];
  volatileLeaves: VolatileUserSettingsPatchLeaf[];
}

export interface UserSettingsSyncStore {
  getSettings: () => PersistedUserSettings;
  getMutationVersion: () => number;
  getPendingPatchBatch: () => {
    patch: PersistedUserSettingsPatch;
    acknowledge: () => boolean;
  } | null;
  getDurableLeafOpId: (leaf: UserSettingsPatchLeaf) => string | null;
  acknowledgeVolatileLeaves: (
    leaves: readonly VolatileUserSettingsPatchLeaf[],
  ) => void;
  withWriteLock: (task: () => Promise<void>) => Promise<boolean>;
  hydrate: (
    settings: PersistedUserSettings,
    expectedVersion: number,
  ) => boolean;
  subscribeMutations: (
    listener: (
      patch: PersistedUserSettingsPatch,
      persistence: UserSettingsMutationPersistence,
    ) => void,
  ) => () => void;
}

/**
 * Coordinates one authenticated user's local fallback with server state.
 *
 * Initial reads are authoritative, except for local edits made after the read
 * starts. Those edits are folded over the server snapshot and written through
 * a serialized queue. PATCH responses never mutate local state, so an older
 * async response cannot roll back a newer click. Failed writes remain in a
 * user-scoped local outbox; the next handshake folds that patch over its GET
 * result before hydration, so reconnect/reload cannot erase the unsynced edit.
 */
export class UserSettingsSyncController {
  private stopped = false;
  private started = false;
  private bootstrapped = false;
  private writeFailed = false;
  private readonly volatileLeaves = new Map<
    UserSettingsPatchLeaf,
    VolatileUserSettingsPatchLeaf
  >();
  private writeTask: Promise<void> | null = null;
  private unsubscribe: (() => void) | null = null;

  constructor(
    private readonly store: UserSettingsSyncStore,
    private readonly transport: UserSettingsTransport,
    initialVolatileLeaves: VolatileUserSettingsPatchLeaf[] = [],
  ) {
    for (const leaf of initialVolatileLeaves) {
      this.volatileLeaves.set(leaf.leaf, leaf);
    }
  }

  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    this.unsubscribe = this.store.subscribeMutations((_patch, persistence) => {
      for (const leaf of persistence.durableLeaves) {
        this.volatileLeaves.delete(leaf);
      }
      for (const leaf of persistence.volatileLeaves) {
        this.volatileLeaves.set(leaf.leaf, leaf);
      }
      this.writeFailed = false;
      if (this.bootstrapped) this.scheduleWrites();
    });
    const hydrationVersion = this.store.getMutationVersion();

    try {
      const acquired = await this.store.withWriteLock(async () => {
        const response = await this.transport.get();
        if (this.stopped) return;

        const baselineResponse =
          response.settings === null
            ? await this.transport.initialize(this.store.getSettings())
            : response;
        this.hydrateResponse(baselineResponse, hydrationVersion);
      });
      if (acquired) {
        this.scheduleWrites();
        return;
      }

      // Web Locks are optional browser functionality. Without them, keep the
      // cross-device read path available but leave PUT/PATCH fail-closed so
      // two tabs cannot race an outbox acknowledgement.
      const response = await this.transport.get();
      this.hydrateResponse(response, hydrationVersion);
    } catch {
      // Offline/auth-refresh/validation failures are intentionally non-fatal.
      // The existing localStorage-backed behavior remains available, and the
      // next authenticated page load tries the handshake again.
    }
  }

  stop(): void {
    this.stopped = true;
    this.unsubscribe?.();
    this.unsubscribe = null;
  }

  async whenIdle(): Promise<void> {
    while (this.writeTask) await this.writeTask;
  }

  private hydrateResponse(
    response: UserSettingsResponse,
    hydrationVersion: number,
  ): void {
    if (this.stopped || response.settings === null) return;
    const desiredPatch = this.composePendingPatch(
      this.store.getPendingPatchBatch(),
    ).patch;
    const desired = desiredPatch
      ? applyPersistedUserSettingsPatch(response.settings, desiredPatch)
      : response.settings;
    this.store.hydrate(desired, hydrationVersion);
    this.bootstrapped = true;
  }

  private composePendingPatch(
    durableBatch: ReturnType<UserSettingsSyncStore["getPendingPatchBatch"]>,
  ): {
    patch: PersistedUserSettingsPatch | null;
    volatileLeaves: VolatileUserSettingsPatchLeaf[];
  } {
    let patch = durableBatch?.patch ?? null;
    const volatileLeaves: VolatileUserSettingsPatchLeaf[] = [];
    const supersededLeaves: VolatileUserSettingsPatchLeaf[] = [];
    for (const [leaf, volatile] of this.volatileLeaves) {
      const currentOpId = this.store.getDurableLeafOpId(leaf);
      if (currentOpId !== volatile.observedDurableOpId) {
        this.volatileLeaves.delete(leaf);
        supersededLeaves.push(volatile);
        continue;
      }
      patch = mergePersistedUserSettingsPatches(patch, volatile.patch);
      volatileLeaves.push(volatile);
    }
    this.store.acknowledgeVolatileLeaves(supersededLeaves);
    return { patch, volatileLeaves };
  }

  private scheduleWrites(): void {
    if (
      this.stopped ||
      !this.bootstrapped ||
      this.writeFailed ||
      this.writeTask
    )
      return;
    this.writeTask = this.drainWrites().finally(() => {
      this.writeTask = null;
      if (
        !this.writeFailed &&
        (this.volatileLeaves.size > 0 ||
          this.store.getPendingPatchBatch() !== null)
      ) {
        this.scheduleWrites();
      }
    });
  }

  private async drainWrites(): Promise<void> {
    while (!this.stopped) {
      let attempted = false;
      let requestFailed = false;
      let acknowledgeFailed = false;
      const acquired = await this.store.withWriteLock(async () => {
        if (this.stopped) return;
        const durableBatch = this.store.getPendingPatchBatch();
        const { patch, volatileLeaves } =
          this.composePendingPatch(durableBatch);
        if (patch === null) return;
        attempted = true;
        try {
          const response = await this.transport.patch(patch);
          if (response.settings === null) {
            const recovered = await this.transport.initialize(
              this.store.getSettings(),
            );
            if (recovered.settings === null) {
              throw new Error(
                "User settings recovery did not initialize a record",
              );
            }
            const reapplied = await this.transport.patch(patch);
            if (reapplied.settings === null) {
              throw new Error(
                "User settings recovery did not retain the pending patch",
              );
            }
          }
        } catch {
          requestFailed = true;
          return;
        }
        if (durableBatch !== null && !durableBatch.acknowledge()) {
          acknowledgeFailed = true;
          return;
        }
        this.store.acknowledgeVolatileLeaves(volatileLeaves);
        for (const volatile of volatileLeaves) {
          if (this.volatileLeaves.get(volatile.leaf) === volatile) {
            this.volatileLeaves.delete(volatile.leaf);
          }
        }
      });
      if (!acquired || requestFailed || acknowledgeFailed) {
        this.writeFailed = true;
        return;
      }
      if (!attempted) return;
    }
  }
}
