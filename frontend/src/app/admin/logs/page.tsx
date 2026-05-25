"use client";

import { useEffect, useState } from "react";

import { AdminScopeBanner } from "@/components/admin/admin-scope-banner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { getAdminLogs } from "@/core/admin/api";
import { isSystemAdminView } from "@/core/admin/scope";
import type { AuditLogEntry } from "@/core/admin/types";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

export default function AdminLogsPage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const isSystemAdmin = isSystemAdminView(user);
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [tenantId, setTenantId] = useState("");
  const [threadId, setThreadId] = useState("");
  const [direction, setDirection] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [page, setPage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 20;

  const refresh = (offset = 0) => {
    getAdminLogs({
      tenant_id: tenantId || undefined,
      thread_id: threadId || undefined,
      direction: direction || undefined,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      limit: pageSize,
      offset,
    })
      .then((res) => {
        setEntries(res.entries);
        setTotal(res.total);
        setPage(Math.floor(offset / pageSize));
      })
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">{t.admin.auditLogs}</h1>
      <AdminScopeBanner />

      {error && (
        <p className="text-sm text-destructive">{t.admin.error}: {error}</p>
      )}

      <div className="flex flex-wrap items-end gap-2">
        {isSystemAdmin && (
          <div>
            <label className="text-xs text-muted-foreground">{t.admin.tenant}</label>
            <Input
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="tenant"
              className="w-32"
            />
          </div>
        )}
        <div>
          <label className="text-xs text-muted-foreground">Thread</label>
          <Input
            value={threadId}
            onChange={(e) => setThreadId(e.target.value)}
            placeholder="thread"
            className="w-32"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">{t.admin.direction}</label>
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
            className="flex h-9 rounded-md border bg-transparent px-3 py-1 text-sm"
          >
            <option value="">{t.admin.all}</option>
            <option value="input">{t.admin.input_dir}</option>
            <option value="output">{t.admin.output_dir}</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground">{t.admin.startDate}</label>
          <Input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">{t.admin.endDate}</label>
          <Input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </div>
        <button
          onClick={() => refresh(0)}
          className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90"
        >
          {t.admin.filter}
        </button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">
            {t.admin.records} ({total} {t.admin.totalRecords.toLowerCase()})
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-4">{t.admin.timestamp}</th>
                  <th className="py-2 pr-4">{t.admin.tenant}</th>
                  <th className="py-2 pr-4">{t.admin.actor}</th>
                  <th className="py-2 pr-4">{t.admin.direction}</th>
                  <th className="py-2 pr-4">{t.admin.model}</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2">Reasons</th>
                </tr>
              </thead>
              <tbody>
                {entries.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-8 text-center text-muted-foreground">
                      {t.admin.noLogRecords}
                    </td>
                  </tr>
                )}
                {entries.map((e, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-2 pr-4 whitespace-nowrap">{e.timestamp.slice(0, 19)}</td>
                    <td className="py-2 pr-4">{e.tenant_id}</td>
                    <td className="py-2 pr-4">{e.actor_username || e.actor_user_id || "-"}</td>
                    <td className="py-2 pr-4">
                      <span className={e.direction === "input" ? "text-blue-500" : "text-green-500"}>
                        {e.direction === "input" ? t.admin.input_dir : t.admin.output_dir}
                      </span>
                    </td>
                    <td className="py-2 pr-4">{e.provider || "-"}</td>
                    <td className="py-2 pr-4">
                      {e.allowed ? (
                        <span className="text-green-600">{t.admin.allowed_status}</span>
                      ) : (
                        <span className="text-red-600 font-medium">{t.admin.blocked}</span>
                      )}
                    </td>
                    <td className="py-2 max-w-xs truncate">{e.reasons.join(", ") || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between text-sm">
              <span>
                {t.admin.page} {page + 1} / {totalPages}
              </span>
              <div className="flex gap-2">
                <button
                  disabled={page === 0}
                  onClick={() => refresh((page - 1) * pageSize)}
                  className="rounded-md border px-3 py-1 text-sm disabled:opacity-50"
                >
                  {t.admin.previous}
                </button>
                <button
                  disabled={page >= totalPages - 1}
                  onClick={() => refresh((page + 1) * pageSize)}
                  className="rounded-md border px-3 py-1 text-sm disabled:opacity-50"
                >
                  {t.admin.next}
                </button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
