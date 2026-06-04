"use client";

import { useEffect, useState } from "react";
import { ArrowLeftIcon } from "@/components/ui/icons";
import { Button } from "@/components/ui/button";
import {
  type CapabilityDetail,
  getCapabilityDetail,
  scopeLabel,
  statusLabel,
  typeLabel,
} from "@/core/capabilities/api";

interface CapabilityDetailViewProps {
  capType: string;
  capName: string;
  onBack: () => void;
}

export function CapabilityDetailView({
  capType,
  capName,
  onBack,
}: CapabilityDetailViewProps) {
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
    return <p className="text-muted-foreground text-sm">加载中...</p>;
  }

  if (error || !detail) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeftIcon className="size-4 mr-1" />
          返回列表
        </Button>
        <p className="text-destructive text-sm">{error || "未找到该能力"}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeftIcon className="size-4 mr-1" />
        返回列表
      </Button>

      <div>
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-bold">{detail.display_name || detail.name}</h3>
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
          <p className="text-muted-foreground mt-2 text-sm">{detail.description}</p>
        )}
      </div>

      <section>
        <h4 className="text-sm font-semibold mb-2">基础属性</h4>
        <div className="grid grid-cols-2 gap-3 border rounded-lg p-3 text-sm">
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

      <section>
        <h4 className="text-sm font-semibold mb-2">作用域</h4>
        <div className="border rounded-lg p-3">
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

      {Object.keys(detail.extensions).length > 0 && (
        <section>
          <h4 className="text-sm font-semibold mb-2">类型属性</h4>
          <div className="border rounded-lg p-3">
            <pre className="text-xs overflow-auto whitespace-pre-wrap bg-muted/50 p-2 rounded">
              {JSON.stringify(detail.extensions, null, 2)}
            </pre>
          </div>
        </section>
      )}

      <section>
        <h4 className="text-sm font-semibold mb-2">最近变更</h4>
        {detail.recent_changes.length === 0 ? (
          <p className="text-sm text-muted-foreground border rounded-lg p-3">
            暂无变更记录。
          </p>
        ) : (
          <div className="border rounded-lg divide-y">
            {detail.recent_changes.map((change, i) => (
              <div key={i} className="flex items-start gap-3 p-2 text-xs">
                <span className="text-muted-foreground whitespace-nowrap">
                  {change.timestamp}
                </span>
                <span className="font-medium min-w-[60px]">{change.actor}</span>
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
