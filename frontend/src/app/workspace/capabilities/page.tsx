"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  type CapabilitySummary,
  getCapabilities,
  scopeLabel,
  statusLabel,
  typeLabel,
} from "@/core/capabilities/api";

const ALL_TYPES = ["model", "skill", "mcp", "connector", "agent"] as const;

export default function CapabilitiesPage() {
  const [caps, setCaps] = useState<CapabilitySummary[]>([]);
  const [activeType, setActiveType] = useState<string>("");
  const [scopeFilter, setScopeFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getCapabilities(activeType || undefined, scopeFilter || undefined)
      .then((data) => setCaps(data.capabilities))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [activeType, scopeFilter]);

  return (
    <div className="flex flex-col h-full p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">平台能力配置</h1>
        <p className="text-muted-foreground mt-1">
          统一查看模型、技能、MCP、连接器和 Agent 的配置状态。只读视图，编辑请使用各模块独立入口。
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="flex gap-1 bg-muted rounded-lg p-1">
          <button
            onClick={() => setActiveType("")}
            className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
              activeType === "" ? "bg-background shadow-sm" : "hover:bg-background/50"
            }`}
          >
            全部
          </button>
          {ALL_TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setActiveType(t)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                activeType === t ? "bg-background shadow-sm" : "hover:bg-background/50"
              }`}
            >
              {typeLabel(t)}
            </button>
          ))}
        </div>

        <select
          value={scopeFilter}
          onChange={(e) => setScopeFilter(e.target.value)}
          className="px-3 py-1.5 text-sm border rounded-md bg-background"
        >
          <option value="">全部作用域</option>
          <option value="GLOBAL">全局</option>
          <option value="TENANT">租户</option>
          <option value="TENANT_OVERRIDE">租户覆盖</option>
        </select>
      </div>

      {/* Content */}
      {loading && <p className="text-muted-foreground">加载中...</p>}
      {error && <p className="text-destructive">加载失败: {error}</p>}

      {!loading && !error && caps.length === 0 && (
        <p className="text-muted-foreground">暂无能力配置数据。</p>
      )}

      {!loading && caps.length > 0 && (
        <div className="overflow-auto border rounded-lg">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 border-b">
              <tr>
                <th className="text-left px-4 py-2 font-medium">名称</th>
                <th className="text-left px-4 py-2 font-medium">类型</th>
                <th className="text-left px-4 py-2 font-medium">作用域</th>
                <th className="text-left px-4 py-2 font-medium">状态</th>
                <th className="text-left px-4 py-2 font-medium">业务 Owner</th>
                <th className="text-left px-4 py-2 font-medium">技术 Owner</th>
              </tr>
            </thead>
            <tbody>
              {caps.map((c) => (
                <tr key={`${c.type}/${c.name}`} className="border-b last:border-0 hover:bg-muted/30">
                  <td className="px-4 py-2">
                    <Link
                      href={`/workspace/capabilities/${c.type}/${encodeURIComponent(c.name)}`}
                      className="text-primary hover:underline font-medium"
                    >
                      {c.display_name || c.name}
                    </Link>
                    {c.description && (
                      <div className="text-muted-foreground text-xs mt-0.5 line-clamp-1">
                        {c.description}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    <span className="inline-block px-2 py-0.5 text-xs rounded bg-muted">
                      {typeLabel(c.type)}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs">{scopeLabel(c.scope)}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`inline-block px-2 py-0.5 text-xs rounded ${
                        c.status === "enabled"
                          ? "bg-green-100 text-green-800"
                          : c.status === "disabled"
                            ? "bg-yellow-100 text-yellow-800"
                            : "bg-red-100 text-red-800"
                      }`}
                    >
                      {statusLabel(c.status)}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs">{c.owner.business || "—"}</td>
                  <td className="px-4 py-2 text-xs">{c.owner.technical || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Summary */}
      {!loading && !error && (
        <p className="text-xs text-muted-foreground">
          共 {caps.length} 项能力
        </p>
      )}
    </div>
  );
}
