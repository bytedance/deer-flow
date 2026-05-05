"use client";

import { OctagonXIcon, ShieldAlertIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { fetchGateway } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";

interface TenantStatus {
  tenant_id: string;
  is_active: boolean;
  name: string;
  found: boolean;
}

async function getTenantStatus(): Promise<TenantStatus> {
  const res = await fetchGateway(`${getBackendBaseURL()}/api/tenant/status`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to fetch tenant status");
  }
  return res.json() as Promise<TenantStatus>;
}

export type TenantGuardResult =
  | { allowed: true }
  | { allowed: false; reason: "disabled" | "not_found" | "error" };

export function useTenantGuard(): { result: TenantGuardResult | null } {
  const router = useRouter();
  const [result, setResult] = useState<TenantGuardResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    getTenantStatus()
      .then((status) => {
        if (!cancelled) {
          if (!status.found) {
            setResult({ allowed: false, reason: "not_found" });
          } else if (!status.is_active) {
            setResult({ allowed: false, reason: "disabled" });
          } else {
            setResult({ allowed: true });
          }
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setResult({ allowed: false, reason: "error" });
          if (
            (err as Error).message.includes("401") ||
            (err as Error).message.includes("403")
          ) {
            router.push("/");
          }
        }
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return { result };
}

export function TenantDisabledPage() {
  const { t } = useI18n();

  return (
    <div className="flex h-full items-center justify-center">
      <div className="max-w-md text-center space-y-4 p-8">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
          <OctagonXIcon className="h-8 w-8 text-destructive" />
        </div>
        <h2 className="text-xl font-semibold">{t.admin.tenantDisabledTitle}</h2>
        <p className="text-sm text-muted-foreground">
          {t.admin.tenantDisabledDesc}
        </p>
      </div>
    </div>
  );
}

export function TenantNotFoundPage() {
  const { t } = useI18n();

  return (
    <div className="flex h-full items-center justify-center">
      <div className="max-w-md text-center space-y-4 p-8">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
          <ShieldAlertIcon className="h-8 w-8 text-destructive" />
        </div>
        <h2 className="text-xl font-semibold">{t.admin.tenantNotFoundTitle}</h2>
        <p className="text-sm text-muted-foreground">
          {t.admin.tenantNotFoundDesc}
        </p>
      </div>
    </div>
  );
}
