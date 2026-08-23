"use client";

import { useEffect, useState } from "react";

import {
  fetchUserSettings,
  initializeUserSettings,
  patchUserSettings,
} from "./api";
import {
  activateBaseSettingsPersistence,
  getBaseSettingsMutationBoundary,
  getBaseSettingsMutationVersion,
  getPendingBaseSettingsLeafOpId,
  getPendingBaseSettingsPatchBatch,
  getPersistedBaseSettingsSnapshot,
  hydrateBaseSettingsFromServer,
  seedPendingBaseSettingsFromCurrent,
  subscribeBaseSettingsMutations,
  withBaseSettingsWriteLock,
} from "./store";
import { UserSettingsSyncController } from "./sync";

function transportForUser(userId: string) {
  return {
    get: () => fetchUserSettings(userId),
    initialize: (settings: Parameters<typeof initializeUserSettings>[1]) =>
      initializeUserSettings(userId, settings),
    patch: (patch: Parameters<typeof patchUserSettings>[1]) =>
      patchUserSettings(userId, patch),
  };
}

export function UserSettingsSync({
  enabled,
  userId,
}: {
  enabled: boolean;
  userId: string;
}) {
  return (
    <UserSettingsSyncLifecycle key={userId} enabled={enabled} userId={userId} />
  );
}

function UserSettingsSyncLifecycle({
  enabled,
  userId,
}: {
  enabled: boolean;
  userId: string;
}) {
  const [activationBoundary] = useState(() =>
    getBaseSettingsMutationBoundary(userId),
  );

  useEffect(() => {
    if (!enabled || !userId) return;
    let cancelled = false;
    let controller: UserSettingsSyncController | null = null;
    let deactivatePersistence: (() => void) | null = null;
    void activateBaseSettingsPersistence(userId).then((deactivate) => {
      if (cancelled) {
        deactivate();
        return;
      }
      const activationVolatileLeaves =
        getBaseSettingsMutationVersion() !== activationBoundary.version &&
        (activationBoundary.userId === null ||
          activationBoundary.userId === userId)
          ? seedPendingBaseSettingsFromCurrent(
              userId,
              activationBoundary.snapshot,
              activationBoundary.durableLeafOpIds,
            )
          : [];
      deactivatePersistence = deactivate;
      const store = {
        getSettings: getPersistedBaseSettingsSnapshot,
        getMutationVersion: getBaseSettingsMutationVersion,
        getPendingPatchBatch: () => getPendingBaseSettingsPatchBatch(userId),
        getDurableLeafOpId: (
          leaf: Parameters<typeof getPendingBaseSettingsLeafOpId>[1],
        ) => getPendingBaseSettingsLeafOpId(userId, leaf),
        withWriteLock: (task: () => Promise<void>) =>
          withBaseSettingsWriteLock(userId, task),
        hydrate: hydrateBaseSettingsFromServer,
        subscribeMutations: subscribeBaseSettingsMutations,
      };
      controller = new UserSettingsSyncController(
        store,
        transportForUser(userId),
        activationVolatileLeaves,
      );
      void controller.start();
    });
    return () => {
      cancelled = true;
      controller?.stop();
      deactivatePersistence?.();
    };
  }, [activationBoundary, enabled, userId]);

  return null;
}
