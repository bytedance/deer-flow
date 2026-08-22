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

export interface UserSettingsSyncStore {
  getSettings: () => PersistedUserSettings;
  getMutationVersion: () => number;
  getPendingPatch: () => PersistedUserSettingsPatch | null;
  setPendingPatch: (patch: PersistedUserSettingsPatch | null) => void;
  hydrate: (
    settings: PersistedUserSettings,
    expectedVersion: number,
  ) => boolean;
  subscribeMutations: (
    listener: (patch: PersistedUserSettingsPatch) => void,
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
  private pendingPatch: PersistedUserSettingsPatch | null = null;
  private inFlightPatch: PersistedUserSettingsPatch | null = null;
  private writeTask: Promise<void> | null = null;
  private unsubscribe: (() => void) | null = null;

  constructor(
    private readonly store: UserSettingsSyncStore,
    private readonly transport: UserSettingsTransport,
  ) {}

  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    this.pendingPatch = this.store.getPendingPatch();
    this.unsubscribe = this.store.subscribeMutations((patch) => {
      this.pendingPatch = mergePersistedUserSettingsPatches(
        this.pendingPatch,
        patch,
      );
      this.writeFailed = false;
      this.persistOutbox();
      if (this.bootstrapped) this.scheduleWrites();
    });

    try {
      const response = await this.transport.get();
      if (this.stopped) return;

      const baselineResponse =
        response.settings === null
          ? await this.transport.initialize(this.store.getSettings())
          : response;
      if (this.stopped || baselineResponse.settings === null) return;

      const expectedVersion = this.store.getMutationVersion();
      const desired = this.pendingPatch
        ? applyPersistedUserSettingsPatch(
            baselineResponse.settings,
            this.pendingPatch,
          )
        : baselineResponse.settings;
      this.store.hydrate(desired, expectedVersion);
      this.bootstrapped = true;
      this.scheduleWrites();
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
      if (this.pendingPatch) this.scheduleWrites();
    });
  }

  private async drainWrites(): Promise<void> {
    while (!this.stopped && this.pendingPatch) {
      const patch = this.pendingPatch;
      this.pendingPatch = null;
      this.inFlightPatch = patch;
      this.persistOutbox();
      try {
        await this.transport.patch(patch);
      } catch {
        this.pendingPatch = mergePersistedUserSettingsPatches(
          patch,
          this.pendingPatch ?? {},
        );
        this.inFlightPatch = null;
        this.writeFailed = true;
        this.persistOutbox();
        return;
      }
      this.inFlightPatch = null;
      this.persistOutbox();
    }
  }

  private persistOutbox(): void {
    const outbox = this.inFlightPatch
      ? mergePersistedUserSettingsPatches(
          this.inFlightPatch,
          this.pendingPatch ?? {},
        )
      : this.pendingPatch;
    this.store.setPendingPatch(outbox);
  }
}
