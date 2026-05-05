"use client";

import { TenantDisabledPage, TenantNotFoundPage, useTenantGuard } from "@/core/tenant/tenant-guard";

export function TenantGuardWrapper({ children }: { children: React.ReactNode }) {
  const { result } = useTenantGuard();

  if (result === null) {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (!result.allowed) {
    return (
      <div className="h-screen">
        {result.reason === "not_found" ? <TenantNotFoundPage /> : <TenantDisabledPage />}
      </div>
    );
  }

  return <>{children}</>;
}
