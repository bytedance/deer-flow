"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  type CapabilityDetail,
  getCapabilityDetail,
  scopeLabel,
  statusLabel,
  typeLabel,
} from "@/core/capabilities/api";

export default function CapabilityDetailPage() {
  const params = useParams<{ type: string; name: string }>();
  const capType = decodeURIComponent(params.type);
  const capName = decodeURIComponent(params.name);

  const [detail, setDetail] = useState<CapabilityDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getCapabilityDetail(capType, capName)
      .then(setDetail)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [capType, capName]);

  if (loading) {
    return (
      <div className="p-6">
        <p className="text-muted-foreground">加载中...</p>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="p-6 space-y-4">
        <Link href="/workspace/capabilities" className="text-sm text-primary hover:underline">
          &larr; 返回能力列表
        </Link>
        <p className="text-destructive">{error || "未找到该能力"}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col p-6 space-y-6 max-w-4xl">
      {/* Back link */}
      <Link href="/workspace/capabilities" className="text-sm text-primary hover:underline">
        &larr; 返回能力列表
      </Link>

      {/* Header */}
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">{detail.display_name || detail.name}</h1>
          <span className="inline-block px-2 py-0.5 text-xs rounded bg-muted">
            {typeLabel(detail.type)}
          </span>
          <span
            className={`inline-block px-2 py-0.5 text-xs rounded ${
              detail.status === "enabled"
                ? "bg-green-100 text-green-800"
                : "bg-yellow-100 text-yellow-800"
            }`}
          >
            {statusLabel(detail.status)}
          </span>
        </div>
        {detail.description && (
          <p className="text-muted-foreground mt-2">{detail.description}</p>
        )}
      </div>

      {/* Base Attributes */}
      <section>
        <h2 className="text-lg font-semibold mb-3">基础属性</h2>
        <div className="grid grid-cols-2 gap-4 border rounded-lg p-4">
          <Field label="名称" value={detail.name} />
          <Field label="类型" value={typeLabel(detail.type)} />
          <Field label="作用域" value={scopeLabel(detail.scope)} />
          <Field label="状态" value={statusLabel(detail.status)} />
          <Field label="业务 Owner" value={detail.owner.business || "—"} />
          <Field label="技术 Owner" value={detail.owner.technical || "—"} />
          {detail.version && <Field label="版本" value={detail.version} />}
          {detail.source && <Field label="来源" value={detail.source} />}
          {detail.tags.length > 0 && (
            <Field label="标签" value={detail.tags.join(", ")} />
          )}
        </div>
      </section>

      {/* Scope */}
      <section>
        <h2 className="text-lg font-semibold mb-3">作用域</h2>
        <div className="border rounded-lg p-4">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block px-3 py-1 text-sm rounded-full ${
                detail.scope === "GLOBAL"
                  ? "bg-blue-100 text-blue-800"
                  : detail.scope === "TENANT"
                    ? "bg-purple-100 text-purple-800"
                    : "bg-orange-100 text-orange-800"
              }`}
            >
              {scopeLabel(detail.scope)}
            </span>
            <span className="text-sm text-muted-foreground">
              {detail.scope === "GLOBAL" && "所有租户共享此能力"}
              {detail.scope === "TENANT" && "每个租户独立配置"}
              {detail.scope === "TENANT_OVERRIDE" && "租户可覆盖全局默认值"}
            </span>
          </div>
        </div>
      </section>

      {/* Type-specific Extensions */}
      {Object.keys(detail.extensions).length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-3">类型属性</h2>
          <div className="border rounded-lg p-4">
            <pre className="text-xs overflow-auto whitespace-pre-wrap bg-muted/50 p-3 rounded">
              {JSON.stringify(detail.extensions, null, 2)}
            </pre>
          </div>
        </section>
      )}

      {/* Recent Changes */}
      <section>
        <h2 className="text-lg font-semibold mb-3">最近变更</h2>
        {detail.recent_changes.length === 0 ? (
          <p className="text-sm text-muted-foreground border rounded-lg p-4">
            暂无变更记录。
          </p>
        ) : (
          <div className="border rounded-lg divide-y">
            {detail.recent_changes.map((change, i) => (
              <div key={i} className="flex items-start gap-4 p-3 text-sm">
                <span className="text-muted-foreground whitespace-nowrap">
                  {change.timestamp}
                </span>
                <span className="font-medium min-w-[80px]">{change.actor}</span>
                <span>{change.summary}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm mt-0.5">{value}</dd>
    </div>
  );
}
