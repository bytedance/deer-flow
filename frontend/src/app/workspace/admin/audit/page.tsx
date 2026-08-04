"use client";

import { useEffect, useState } from "react";

import { AdminSection } from "@/components/admin/admin-section";
import { fetch } from "@/core/api/fetcher";

type AuditLog = {
  id: string;
  actor_user_id: string | null;
  action: string;
  target_type: string;
  target_id: string;
  reason: string | null;
  created_at: string;
};

export default function AuditPage() {
  const [items, setItems] = useState<AuditLog[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetch("/api/admin/safety/audit")
      .then(async (response) => {
        if (!response.ok) throw new Error("无法加载审计日志");
        return response.json() as Promise<{ items: AuditLog[] }>;
      })
      .then((data) => setItems(data.items))
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : "无法加载审计日志"),
      );
  }, []);

  return (
    <AdminSection
      title="审计日志"
      description="记录内容安全检测与管理员处置操作；不展示原始提示词或模型输出。"
    >
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <div className="divide-y border-y">
        {items.length === 0 ? (
          <p className="text-muted-foreground py-6 text-sm">暂无审计记录。</p>
        ) : (
          items.map((item) => (
            <article
              className="grid gap-1 py-4 md:grid-cols-[1fr_auto]"
              key={item.id}
            >
              <div>
                <p className="text-sm font-medium">{item.action}</p>
                <p className="text-muted-foreground mt-1 text-xs">
                  {item.target_type} · {item.target_id} · 操作人{" "}
                  {item.actor_user_id ?? "系统"}
                </p>
                {item.reason ? (
                  <p className="text-muted-foreground mt-1 text-sm">
                    原因：{item.reason}
                  </p>
                ) : null}
              </div>
              <time className="text-muted-foreground text-xs">
                {new Date(item.created_at).toLocaleString()}
              </time>
            </article>
          ))
        )}
      </div>
    </AdminSection>
  );
}
