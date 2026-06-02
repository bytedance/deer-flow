"use client";

import { useCallback, useEffect, useState } from "react";

import type { InteractionState } from "@/core/genui/store";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AbnormalItem {
  abnormal_id: string;
  mac_path: string;
  mac_name: string;
  component_name: string;
  mac_id: string;
  component_id: string;
  latest_level: number;
  serious_level: number;
  first_event_time: number;
}

interface AbnormalListSelectorBlockProps {
  block: {
    block_id?: string;
    props: {
      title?: string;
      org_id?: number;
      page_size?: number;
    };
    callback_id?: string;
    interactionState?: InteractionState;
    onInteraction?: (
      callbackId: string,
      payload: Record<string, unknown>,
      blockId?: string,
    ) => void;
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const LEVEL_MAP: Record<number, string> = {
  0: "0",
  9: "P",
  10: "P1",
  11: "P1+",
  20: "P2",
  21: "P2+",
  30: "P3",
  31: "P3+",
  40: "P4",
  41: "P4+",
};

function formatLevel(level: number): string {
  return LEVEL_MAP[level] ?? String(level);
}

function getLevelStyle(level: number): string {
  if (level >= 40) return "bg-red-100 text-red-700 font-bold";
  if (level >= 30) return "bg-orange-100 text-orange-700 font-semibold";
  if (level >= 20) return "bg-yellow-100 text-yellow-700";
  if (level >= 10) return "bg-blue-100 text-blue-700";
  return "bg-gray-100 text-gray-500";
}

function getBaseUrl(): string {
  if (typeof window !== "undefined") {
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

function formatTimestamp(ms: number): string {
  try {
    return new Date(ms).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return String(ms);
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AbnormalListSelectorBlock({
  block,
}: AbnormalListSelectorBlockProps) {
  const { block_id, props, callback_id, interactionState, onInteraction } =
    block;
  const { title, org_id = 0, page_size = 5 } = props;

  const [items, setItems] = useState<AbnormalItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const isDisabled =
    interactionState?.status === "loading" ||
    interactionState?.status === "submitted" ||
    interactionState?.status === "expired" ||
    interactionState?.status === "readonly";

  const fetchList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("current_page", String(page));
      params.set("page_size", String(page_size));
      params.set("org_id", String(org_id));
      const baseUrl = getBaseUrl();
      const res = await fetch(
        `${baseUrl}/api/abnormal/list?${params.toString()}`,
      );
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      const list: AbnormalItem[] = Array.isArray(data.items) ? data.items : [];
      setItems(list);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to fetch abnormal list",
      );
    } finally {
      setLoading(false);
    }
  }, [org_id, page_size, page]);

  useEffect(() => {
    void fetchList();
  }, [fetchList]);

  const handleSelect = (item: AbnormalItem) => {
    if (isDisabled) return;
    setSelectedId(item.abnormal_id);
    if (callback_id && onInteraction) {
      onInteraction(
        callback_id,
        {
          selected: {
            abnormal_id: item.abnormal_id,
            mac_id: item.mac_id,
            component_id: item.component_id,
            mac_name: item.mac_name,
            component_name: item.component_name,
            mac_path: item.mac_path,
            mac_type: 1,
          },
        },
        block_id,
      );
    }
  };

  // ---- submitted ----
  if (interactionState?.status === "submitted") {
    return null;
  }

  // ---- expired ----
  if (interactionState?.status === "expired") {
    return (
      <div
        className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 dark:border-yellow-800 dark:bg-yellow-950"
        role="status"
      >
        <p className="text-sm text-yellow-800 dark:text-yellow-200">
          该选择器已过期。
        </p>
      </div>
    );
  }

  // ---- normal / loading / error ----
  return (
    <div
      className="rounded-lg border bg-card p-4"
      role="region"
      aria-label={title ?? "异常列表选择器"}
    >
      {title && <h3 className="mb-3 text-sm font-medium">{title}</h3>}

      {(() => {
        if (loading) {
          return (
            <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">
              正在加载异常列表…
            </div>
          );
        }
        if (error) {
          return (
            <div className="flex h-40 flex-col items-center justify-center gap-2 text-xs text-red-600">
              <span>加载失败: {error}</span>
              <button
                type="button"
                className="underline"
                onClick={() => void fetchList()}
              >
                重试
              </button>
            </div>
          );
        }
        if (items.length === 0) {
          return (
            <div className="flex h-40 items-center justify-center text-xs text-muted-foreground">
              当前无异常记录
            </div>
          );
        }

        return (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th className="py-2 px-3 text-left font-medium">设备</th>
                    <th className="py-2 px-3 text-left font-medium">子设备</th>
                    <th className="py-2 px-3 text-center font-medium w-16">等级</th>
                    <th className="py-2 px-3 text-left font-medium w-32">首次异常</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr
                      key={item.abnormal_id}
                      className={`cursor-pointer border-b transition-colors hover:bg-muted/50 ${
                        selectedId === item.abnormal_id
                          ? "bg-primary/10 font-medium"
                          : ""
                      }`}
                      onClick={() => handleSelect(item)}
                    >
                      <td className="py-2 px-3">
                        <div className="max-w-[200px] truncate" title={item.mac_name}>
                          {item.mac_name}
                        </div>
                        <div
                          className="max-w-[200px] truncate text-xs text-muted-foreground"
                          title={item.mac_path}
                        >
                          {item.mac_path}
                        </div>
                      </td>
                      <td className="py-2 px-3 max-w-[120px] truncate">
                        {item.component_name}
                      </td>
                      <td className="py-2 px-3 text-center">
                        <span
                          className={`rounded px-2 py-0.5 text-xs ${getLevelStyle(item.serious_level)}`}
                        >
                          {formatLevel(item.serious_level)}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-xs">
                        {formatTimestamp(item.first_event_time)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="mt-3 flex items-center justify-center gap-2 text-xs">
              <button
                type="button"
                className="rounded border px-2 py-1 hover:bg-muted disabled:opacity-30"
                disabled={page <= 1 || isDisabled}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </button>
              <span className="text-muted-foreground">第 {page} 页</span>
              <button
                type="button"
                className="rounded border px-2 py-1 hover:bg-muted disabled:opacity-30"
                disabled={items.length < page_size || isDisabled}
                onClick={() => setPage((p) => p + 1)}
              >
                下一页
              </button>
            </div>
          </>
        );
      })()}

      {interactionState?.status === "error" && (
        <p className="mt-2 text-xs text-red-600" role="alert">
          {interactionState.error}
        </p>
      )}
    </div>
  );
}
