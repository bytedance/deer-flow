import { useCallback, useSyncExternalStore } from "react";

import { getCurrentTenantId, setCurrentTenantId, subscribe } from "./store";
import { DEFAULT_TENANT_ID } from "./types";

export function useTenant(): [string, (id: string) => void] {
  const tenantId = useSyncExternalStore(
    subscribe,
    getCurrentTenantId,
    () => DEFAULT_TENANT_ID,
  );

  const setTenant = useCallback((id: string) => {
    setCurrentTenantId(id);
  }, []);

  return [tenantId, setTenant];
}
