"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AdminSection } from "@/components/admin/admin-section";
import { Button } from "@/components/ui/button";
import { fetch } from "@/core/api/fetcher";

type Tenant = {
  id: string;
  email: string;
  system_role: string;
  is_frozen: boolean;
  available_credits: number;
};

export default function TenantsPage() {
  const [items, setItems] = useState<Tenant[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<Tenant | null>(null);
  const [credits, setCredits] = useState("100");
  const [reason, setReason] = useState("");
  const load = useCallback(() => {
    void fetch("/api/admin/users")
      .then((response) =>
        response.ok ? (response.json() as Promise<Tenant[]>) : [],
      )
      .then(setItems);
  }, []);
  useEffect(() => load(), [load]);
  const changeCredits = async (event: FormEvent) => {
    event.preventDefault();
    if (!editing) return;
    const response = await fetch(`/api/admin/users/${editing.id}/credits`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credits: Number(credits), reason }),
    });
    setNotice(
      response.ok
        ? "积分已调整并写入审计日志。"
        : "积分调整失败，请检查余额和输入。 ",
    );
    if (response.ok) {
      setEditing(null);
      setReason("");
      load();
    }
  };
  const changeFreeze = async (tenant: Tenant) => {
    const response = await fetch(
      `/api/admin/users/${tenant.id}/freeze?frozen=${!tenant.is_frozen}`,
      { method: "POST" },
    );
    setNotice(
      response.ok
        ? `账号已${tenant.is_frozen ? "恢复" : "冻结"}。`
        : "账号状态更新失败。",
    );
    if (response.ok) load();
  };
  return (
    <AdminSection
      title="租户与用户"
      description="每个注册用户均为独立租户。可调整余额、冻结或恢复账号，操作会记录审计日志。"
    >
      {notice ? <p className="text-sm">{notice}</p> : null}
      <div className="divide-y border-y">
        {items.length === 0 ? (
          <p className="text-muted-foreground py-6 text-sm">暂无租户。</p>
        ) : (
          items.map((tenant) => (
            <article
              className="flex flex-wrap items-center justify-between gap-3 py-4"
              key={tenant.id}
            >
              <div>
                <p className="text-sm font-medium">{tenant.email}</p>
                <p className="text-muted-foreground text-xs">
                  {tenant.system_role} · {tenant.is_frozen ? "已冻结" : "正常"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm tabular-nums">
                  {tenant.available_credits} 积分
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setEditing(tenant);
                    setCredits("100");
                    setReason("");
                  }}
                >
                  调积分
                </Button>
                <Button
                  size="sm"
                  variant={tenant.is_frozen ? "outline" : "destructive"}
                  onClick={() => void changeFreeze(tenant)}
                >
                  {tenant.is_frozen ? "恢复" : "冻结"}
                </Button>
              </div>
            </article>
          ))
        )}
      </div>
      {editing ? (
        <form
          className="bg-muted/30 space-y-3 rounded-lg border p-4"
          onSubmit={changeCredits}
        >
          <p className="text-sm font-medium">调整 {editing.email} 的积分</p>
          <label className="text-muted-foreground block text-xs">
            积分变动（负数为扣减）
            <input
              className="text-foreground bg-background mt-1 h-8 w-full border px-2 text-sm"
              required
              type="number"
              value={credits}
              onChange={(event) => setCredits(event.target.value)}
            />
          </label>
          <label className="text-muted-foreground block text-xs">
            调整原因
            <textarea
              className="text-foreground bg-background mt-1 min-h-20 w-full border p-2 text-sm"
              required
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <div className="flex gap-2">
            <Button size="sm" type="submit">
              确认调整
            </Button>
            <Button
              size="sm"
              type="button"
              variant="outline"
              onClick={() => setEditing(null)}
            >
              取消
            </Button>
          </div>
        </form>
      ) : null}
    </AdminSection>
  );
}
