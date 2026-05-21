"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import type { InteractionState } from "@/core/genui/store";

import type { DeviceQueryParams, OrgTreeNode, SelectedDevice } from "./device-selector-types";
import { collectDevices } from "./device-selector-utils";
import OrgTreePanel from "./OrgTreePanel";

interface DeviceSelectorMultiBlockProps {
  block: {
    block_id?: string;
    props: {
      title?: string;
      queryParams?: DeviceQueryParams;
      maxSelect?: number;
      filterDeviceType?: number;
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

function getBaseUrl(): string {
  if (typeof window !== "undefined") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

const DEVICE_TYPE_LABELS: Record<number, string> = {
  1: "旋转机组",
  4: "机泵",
  6: "静设备",
  9: "往复机组",
};

export default function DeviceSelectorMultiBlock({ block }: DeviceSelectorMultiBlockProps) {
  const { block_id, props, callback_id, interactionState, onInteraction } = block;
  const { title, queryParams, maxSelect, filterDeviceType } = props;
  const { user } = useAuth();

  const [treeData, setTreeData] = useState<OrgTreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [selectedOrgNode, setSelectedOrgNode] = useState<OrgTreeNode | null>(null);
  const [selectedDevices, setSelectedDevices] = useState<Map<string, SelectedDevice>>(new Map());

  const isDisabled =
    interactionState?.status === "loading" ||
    interactionState?.status === "submitted" ||
    interactionState?.status === "expired" ||
    interactionState?.status === "readonly";

  const fetchTree = useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    try {
      const params = new URLSearchParams();
      const userId = queryParams?.userId ?? user?.id ?? "1";
      params.set("userId", userId);
      params.set("orgId", String(queryParams?.orgId ?? 0));
      params.set("treeType", String(queryParams?.treeType ?? 1));
      if (queryParams?.typeId != null) {
        params.set("typeId", String(queryParams.typeId));
      }
      const baseUrl = getBaseUrl();
      const res = await fetch(`${baseUrl}/api/organize/tree?${params.toString()}`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      setTreeData(Array.isArray(data) ? data : []);
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : "Failed to fetch tree");
    } finally {
      setLoading(false);
    }
  }, [queryParams?.userId, queryParams?.orgId, queryParams?.treeType, queryParams?.typeId, user]);

  useEffect(() => {
    void fetchTree();
  }, [fetchTree]);

  const devices = useMemo(() => {
    if (!selectedOrgNode) return [];
    return collectDevices(selectedOrgNode, filterDeviceType);
  }, [selectedOrgNode, filterDeviceType]);

  const selectedList = useMemo(() => Array.from(selectedDevices.values()), [selectedDevices]);

  const atMax = maxSelect != null && selectedDevices.size >= maxSelect;

  const handleToggleDevice = (device: OrgTreeNode) => {
    if (isDisabled) return;
    setSelectedDevices((prev) => {
      const next = new Map(prev);
      if (next.has(device.id)) {
        next.delete(device.id);
      } else {
        if (maxSelect != null && next.size >= maxSelect) return prev;
        next.set(device.id, {
          id: device.id,
          label: device.label,
          type: device.type,
          path: device.path,
        });
      }
      return next;
    });
  };

  const handleSubmit = () => {
    if (selectedDevices.size === 0) return;
    if (callback_id && onInteraction) {
      onInteraction(callback_id, { selected: selectedList }, block_id);
    }
  };

  const handleSelectAll = () => {
    if (isDisabled) return;
    setSelectedDevices((prev) => {
      const next = new Map(prev);
      for (const device of devices) {
        if (maxSelect != null && next.size >= maxSelect) break;
        next.set(device.id, {
          id: device.id,
          label: device.label,
          type: device.type,
          path: device.path,
        });
      }
      return next;
    });
  };

  const handleDeselectAll = () => {
    if (isDisabled) return;
    setSelectedDevices(new Map());
  };

  const allCurrentSelected =
    devices.length > 0 && devices.every((d) => selectedDevices.has(d.id));

  if (interactionState?.status === "submitted") {
    return null;
  }

  if (interactionState?.status === "expired") {
    return (
      <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 dark:border-yellow-800 dark:bg-yellow-950" role="status">
        <p className="text-sm text-yellow-800 dark:text-yellow-200">This selector has expired.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-4" role="region" aria-label={title ?? "设备多选选择器"}>
      {title && <h3 className="mb-2 text-sm font-medium">{title}</h3>}

      {loading ? (
        <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">
          加载组织树中...
        </div>
      ) : fetchError ? (
        <div className="flex h-80 items-center justify-center text-xs text-red-600">
          加载失败: {fetchError}
          <button
            type="button"
            className="ml-2 underline"
            onClick={fetchTree}
          >
            重试
          </button>
        </div>
      ) : (
        <div className="flex h-80 gap-3">
          {/* Left: Org Tree */}
          <div className="w-1/2 overflow-hidden rounded-md border">
            <OrgTreePanel
              treeData={treeData}
              onSelectOrgNode={setSelectedOrgNode}
              selectedOrgId={selectedOrgNode?.id}
              disabled={isDisabled}
            />
          </div>

          {/* Right: Device Checkbox List */}
          <div className="flex w-1/2 flex-col overflow-hidden rounded-md border">
            {!selectedOrgNode ? (
              <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                请选择组织节点
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2 border-b px-2 py-1.5">
                  <label className="flex cursor-pointer items-center gap-1.5 text-xs">
                    <input
                      type="checkbox"
                      checked={allCurrentSelected}
                      onChange={() =>
                        allCurrentSelected ? handleDeselectAll() : handleSelectAll()
                      }
                      disabled={isDisabled}
                      className="rounded border"
                    />
                    全选 ({devices.length})
                  </label>
                </div>
                <div className="flex-1 overflow-y-auto">
                  {devices.length === 0 ? (
                    <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                      该组织节点下无设备
                    </div>
                  ) : (
                    <div className="space-y-0">
                      {devices.map((device) => {
                        const checked = selectedDevices.has(device.id);
                        const disabled = isDisabled || (!checked && atMax);
                        return (
                          <label
                            key={device.id}
                            className={`flex cursor-pointer items-center gap-2 px-2 py-1.5 text-xs hover:bg-muted/50 ${
                              disabled && !checked ? "opacity-50" : ""
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => handleToggleDevice(device)}
                              disabled={!!disabled}
                              className="rounded border"
                            />
                            <span>{device.label}</span>
                            {device.type in DEVICE_TYPE_LABELS && (
                              <span className="text-muted-foreground">
                                ({DEVICE_TYPE_LABELS[device.type]})
                              </span>
                            )}
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
                <div className="flex items-center justify-between border-t px-2 py-2">
                  <span className="text-xs text-muted-foreground">
                    已选: {selectedDevices.size}
                    {maxSelect ? ` / ${maxSelect}` : ""}
                  </span>
                  <button
                    type="button"
                    className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                    onClick={handleSubmit}
                    disabled={isDisabled || selectedDevices.size === 0}
                  >
                    {interactionState?.status === "loading" ? "提交中..." : "确认选择"}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {interactionState?.status === "error" && (
        <p className="mt-2 text-xs text-red-600" role="alert">{interactionState.error}</p>
      )}
    </div>
  );
}
