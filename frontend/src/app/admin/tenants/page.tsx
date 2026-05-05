"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  createTenant,
  deleteTenant,
  listTenants,
  updateTenant,
} from "@/core/admin/api";
import type { TenantSummary } from "@/core/admin/types";
import { useI18n } from "@/core/i18n/hooks";

export default function AdminTenantsPage() {
  const { t } = useI18n();
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [newName, setNewName] = useState("");
  const [newId, setNewId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editDailyQuota, setEditDailyQuota] = useState("");
  const [editMonthlyQuota, setEditMonthlyQuota] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const refresh = () => {
    listTenants()
      .then(setTenants)
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleCreate = async () => {
    if (!newId.trim()) {
      setError("请输入租户 ID");
      return;
    }
    if (!newName.trim()) {
      setError("请输入显示名称");
      return;
    }
    try {
      await createTenant({ tenant_id: newId.trim(), name: newName.trim() });
      setNewId("");
      setNewName("");
      setError(null);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleToggleActive = async (tenant: TenantSummary) => {
    try {
      await updateTenant(tenant.tenant_id, { is_active: !tenant.is_active });
      setError(null);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const startEdit = (tenant: TenantSummary) => {
    setEditingId(tenant.tenant_id);
    setEditName(tenant.name);
    setEditDailyQuota(String(tenant.daily_quota_usd));
    setEditMonthlyQuota(String(tenant.monthly_quota_usd));
  };

  const cancelEdit = () => {
    setEditingId(null);
  };

  const handleSave = async (tenantId: string) => {
    try {
      const fields: Record<string, unknown> = {};
      if (editName.trim()) fields.name = editName.trim();
      const daily = parseFloat(editDailyQuota);
      if (!isNaN(daily) && daily >= 0) fields.daily_quota_usd = daily;
      const monthly = parseFloat(editMonthlyQuota);
      if (!isNaN(monthly) && monthly >= 0) fields.monthly_quota_usd = monthly;
      await updateTenant(tenantId, fields);
      setEditingId(null);
      setError(null);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleDelete = async (tenantId: string) => {
    try {
      await deleteTenant(tenantId);
      setDeleteConfirm(null);
      setError(null);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{t.admin.tenants}</h1>

      {error && (
        <p className="text-sm text-destructive">
          {t.admin.error}: {error}
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">
            {t.admin.createTenant}
          </CardTitle>
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
          <Button
            onClick={handleCreate}
            disabled={!newId.trim() || !newName.trim()}
          >
            {t.admin.create}
          </Button>
        </CardContent>
      </Card>

      <div className="space-y-2">
        {tenants.map((tenant) => {
          const isEditing = editingId === tenant.tenant_id;
          const isConfirming = deleteConfirm === tenant.tenant_id;

          return (
            <Card key={tenant.tenant_id}>
              <CardContent className="py-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    {isEditing ? (
                      <Input
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        className="max-w-xs"
                      />
                    ) : (
                      <>
                        <p className="font-medium">{tenant.name}</p>
                        <p className="text-xs text-muted-foreground">
                          ID: {tenant.tenant_id}
                        </p>
                      </>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {isEditing ? (
                      <>
                        <Button size="sm" onClick={() => handleSave(tenant.tenant_id)}>
                          {t.admin.save}
                        </Button>
                        <Button size="sm" variant="outline" onClick={cancelEdit}>
                          {t.admin.cancel}
                        </Button>
                      </>
                    ) : (
                      <>
                        <span className="text-sm text-muted-foreground">
                          {tenant.user_count} {t.admin.users}
                        </span>
                        <span className="text-sm text-muted-foreground">
                          {tenant.thread_count} {t.admin.threads}
                        </span>
                        <span className="text-sm text-muted-foreground">
                          ${tenant.cost_month.toFixed(2)}/mo
                        </span>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleToggleActive(tenant)}
                        >
                          {tenant.is_active ? t.admin.active : t.admin.inactive}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => startEdit(tenant)}
                        >
                          {t.admin.edit}
                        </Button>
                        {tenant.tenant_id !== "default" && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setDeleteConfirm(tenant.tenant_id)}
                          >
                            {t.admin.delete}
                          </Button>
                        )}
                      </>
                    )}
                  </div>
                </div>

                {isEditing && (
                  <div className="flex gap-4 items-end">
                    <div className="space-y-1">
                      <label className="text-xs text-muted-foreground">
                        {t.admin.dailyQuota}
                      </label>
                      <Input
                        type="number"
                        min="0"
                        step="0.01"
                        value={editDailyQuota}
                        onChange={(e) => setEditDailyQuota(e.target.value)}
                        className="max-w-[160px]"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-muted-foreground">
                        {t.admin.monthlyQuota}
                      </label>
                      <Input
                        type="number"
                        min="0"
                        step="0.01"
                        value={editMonthlyQuota}
                        onChange={(e) => setEditMonthlyQuota(e.target.value)}
                        className="max-w-[160px]"
                      />
                    </div>
                  </div>
                )}

                {isConfirming && (
                  <div className="flex items-center gap-2 rounded border border-destructive/50 bg-destructive/10 p-3">
                    <p className="text-sm flex-1">
                      {t.admin.confirmDeleteDesc}
                    </p>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => handleDelete(tenant.tenant_id)}
                    >
                      {t.admin.confirmDelete}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setDeleteConfirm(null)}
                    >
                      {t.admin.cancel}
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
