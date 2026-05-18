"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { InteractionState } from "@/core/genui/store";

import type { DeviceQueryParams, OrgTreeNode, SelectedDevice } from "./device-selector-types";
import OrgTreePanel from "./OrgTreePanel";

interface DeviceSelectorBlockProps {
  block: {
    block_id?: string;
    props: {
      title?: string;
      queryParams?: DeviceQueryParams;
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

function collectDevices(node: OrgTreeNode): OrgTreeNode[] {
  const devices: OrgTreeNode[] = [];
  if (node.children) {
    for (const child of node.children) {
      if (child.type < 10) {
        devices.push(child);
      }
      if (child.children) {
        devices.push(...collectDevices(child));
      }
    }
  }
  return devices.sort((a, b) => (a.displayOrder ?? 0) - (b.displayOrder ?? 0));
}

const DEVICE_TYPE_LABELS: Record<number, string> = {
  1: "旋转机组",
  4: "机泵",
  6: "静设备",
  9: "往复机组",
};

function getBaseUrl(): string {
  if (typeof window !== "undefined") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

export default function DeviceSelectorBlock({ block }: DeviceSelectorBlockProps) {
  const { block_id, props, callback_id, interactionState, onInteraction } = block;
  const { title, queryParams } = props;

  const [treeData, setTreeData] = useState<OrgTreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [selectedOrgNode, setSelectedOrgNode] = useState<OrgTreeNode | null>(null);
  const [selectedDevice, setSelectedDevice] = useState<SelectedDevice | null>(null);

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
      params.set("userId", String(queryParams?.userId ?? 1));
      params.set("orgId", String(queryParams?.orgId ?? 0));
      params.set("treeType", String(queryParams?.treeType ?? 1));
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
  }, [queryParams?.userId, queryParams?.orgId, queryParams?.treeType]);

  useEffect(() => {
    void fetchTree();
  }, [fetchTree]);

  const devices = useMemo(() => {
    if (!selectedOrgNode) return [];
    return collectDevices(selectedOrgNode);
  }, [selectedOrgNode]);

  const handleDeviceClick = (device: OrgTreeNode) => {
    if (isDisabled) return;
    const selected: SelectedDevice = {
      id: device.id,
      label: device.label,
      type: device.type,
      path: device.path,
    };
    setSelectedDevice(selected);
    if (callback_id && onInteraction) {
      onInteraction(callback_id, { selected }, block_id);
    }
  };

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
    <div className="rounded-lg border bg-card p-4" role="region" aria-label={title ?? "设备选择器"}>
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

          {/* Right: Device List */}
          <div className="w-1/2 overflow-y-auto rounded-md border p-2">
            {!selectedOrgNode ? (
              <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                请选择组织节点
              </div>
            ) : devices.length === 0 ? (
              <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                该组织节点下无设备
              </div>
            ) : (
              <div className="space-y-1">
                {devices.map((device) => (
                  <button
                    key={device.id}
                    type="button"
                    className={`w-full rounded px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted/50 disabled:opacity-50 ${
                      selectedDevice?.id === device.id ? "bg-primary/10 font-medium text-primary" : ""
                    }`}
                    onClick={() => handleDeviceClick(device)}
                    disabled={isDisabled}
                  >
                    <span>{device.label}</span>
                    {device.type in DEVICE_TYPE_LABELS && (
                      <span className="ml-2 text-muted-foreground">
                        ({DEVICE_TYPE_LABELS[device.type]})
                      </span>
                    )}
                  </button>
                ))}
              </div>
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
