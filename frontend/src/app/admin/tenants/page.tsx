"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { createTenant, listTenants, updateTenant } from "@/core/admin/api";
import type { TenantSummary } from "@/core/admin/types";
import { useI18n } from "@/core/i18n/hooks";

export default function AdminTenantsPage() {
  const { t } = useI18n();
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [newName, setNewName] = useState("");
  const [newId, setNewId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    listTenants()
      .then(setTenants)
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleCreate = async () => {
    if (!newId.trim() || !newName.trim()) return;
    try {
      await createTenant({ tenant_id: newId.trim(), name: newName.trim() });
      setNewId("");
      setNewName("");
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleToggleActive = async (tenant: TenantSummary) => {
    try {
      await updateTenant(tenant.tenant_id, { name: tenant.name });
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{t.admin.tenants}</h1>

      {error && (
        <p className="text-sm text-destructive">{t.admin.error}: {error}</p>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">{t.admin.createTenant}</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-2">
          <Input
            placeholder={t.admin.tenantIdPlaceholder}
            value={newId}
            onChange={(e) => setNewId(e.target.value)}
            className="max-w-xs"
          />
          <Input
            placeholder={t.admin.displayNamePlaceholder}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="max-w-xs"
          />
          <Button onClick={handleCreate} disabled={!newId.trim() || !newName.trim()}>
            {t.admin.create}
          </Button>
        </CardContent>
      </Card>

      <div className="space-y-2">
        {tenants.map((tenant) => (
          <Card key={tenant.tenant_id}>
            <CardContent className="flex items-center justify-between py-4">
              <div>
                <p className="font-medium">{tenant.name}</p>
                <p className="text-xs text-muted-foreground">ID: {tenant.tenant_id}</p>
              </div>
              <div className="flex items-center gap-4 text-sm text-muted-foreground">
                <span>{tenant.user_count} {t.admin.users}</span>
                <span>{tenant.thread_count} {t.admin.threads}</span>
                <span>${tenant.cost_month.toFixed(2)}/mo</span>
                <Button variant="outline" size="sm" onClick={() => handleToggleActive(tenant)}>
                  {tenant.is_active ? t.admin.active : t.admin.inactive}
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
