"use client";

import { useAuth } from "@/core/auth/AuthProvider";
import { isSystemAdminView } from "@/core/admin/scope";
import { useI18n } from "@/core/i18n/hooks";

export function AdminScopeBanner() {
  const { user } = useAuth();
  const { t } = useI18n();

  if (!user) {
    return null;
  }

  const isSystemAdmin = isSystemAdminView(user);

  return (
    <div className="rounded-lg border bg-muted/40 px-4 py-3 text-sm">
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <p>
          <span className="text-muted-foreground">{t.admin.currentTenant}:</span>{" "}
          {user.tenant_id}
        </p>
        <p>
          <span className="text-muted-foreground">{t.admin.currentScope}:</span>{" "}
          {isSystemAdmin ? t.admin.globalScope : t.admin.tenantScope}
        </p>
      </div>
      <p className="mt-2 text-muted-foreground">
        {isSystemAdmin ? t.admin.globalScopeView : t.admin.tenantScopedView}
      </p>
    </div>
  );
}
