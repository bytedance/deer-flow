"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import type { InteractionState } from "@/core/genui/store";
import { useI18n } from "@/core/i18n/hooks";

import type { DeviceQueryParams, OrgTreeNode } from "./device-selector-types";
import OrgTreePanel from "./OrgTreePanel";

interface SubDeviceSelectorBlockProps {
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

interface SubDeviceItem {
  id: string;
  name: string;
  type: number;
  machineId: string;
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

const SUB_DEVICE_TYPE_FILTER: Record<number, number[]> = {
  1: [80],
  4: [50],
  9: [100, 110],
};

function getBaseUrl(): string {
  if (typeof window !== "undefined") {
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

export default function SubDeviceSelectorBlock({ block }: SubDeviceSelectorBlockProps) {
  const { t } = useI18n();
  const { block_id, props, callback_id, interactionState, onInteraction } = block;

  const DEVICE_TYPE_LABELS: Record<number, string> = {
    1: t.genui.deviceTypeRotating,
    4: t.genui.deviceTypePump,
    6: t.genui.deviceTypeStatic,
    9: t.genui.deviceTypeReciprocating,
  };
  const { title, queryParams } = props;
  const { user } = useAuth();

  const [treeData, setTreeData] = useState<OrgTreeNode[]>([]);
  const [treeLoading, setTreeLoading] = useState(true);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [selectedOrgNode, setSelectedOrgNode] = useState<OrgTreeNode | null>(null);
  const [selectedParentDevice, setSelectedParentDevice] = useState<OrgTreeNode | null>(null);

  const [subDevices, setSubDevices] = useState<SubDeviceItem[]>([]);
  const [subLoading, setSubLoading] = useState(false);
  const [subError, setSubError] = useState<string | null>(null);
  const [selectedSubDevice, setSelectedSubDevice] = useState<SubDeviceItem | null>(null);

  const isDisabled =
    interactionState?.status === "loading" ||
    interactionState?.status === "submitted" ||
    interactionState?.status === "expired" ||
    interactionState?.status === "readonly";

  const fetchTree = useCallback(async () => {
    setTreeLoading(true);
    setTreeError(null);
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
      setTreeError(e instanceof Error ? e.message : "Failed to fetch tree");
    } finally {
      setTreeLoading(false);
    }
  }, [queryParams?.userId, queryParams?.orgId, queryParams?.treeType, queryParams?.typeId, user]);

  useEffect(() => {
    void fetchTree();
  }, [fetchTree]);

  const devices = useMemo(() => {
    if (!selectedOrgNode) return [];
    return collectDevices(selectedOrgNode);
  }, [selectedOrgNode]);

  const filteredSubDevices = useMemo(() => {
    if (!selectedParentDevice) return [];
    const allowedTypes = SUB_DEVICE_TYPE_FILTER[selectedParentDevice.type];
    if (!allowedTypes) return subDevices;
    return subDevices.filter((d) => allowedTypes.includes(d.type));
  }, [selectedParentDevice, subDevices]);

  const handleParentDeviceClick = async (device: OrgTreeNode) => {
    if (isDisabled) return;
    setSelectedParentDevice(device);
    setSelectedSubDevice(null);
    setSubError(null);
    setSubLoading(true);
    try {
      const baseUrl = getBaseUrl();
      const res = await fetch(`${baseUrl}/api/machine/component-info?machineId=${device.id}`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      const list = Array.isArray(data) ? data : [];
      setSubDevices(
        list.map((item: any) => ({
          id: String(item.id),
          name: item.name ?? "",
          type: item.type ?? 0,
          machineId: String(item.machineId ?? device.id),
        })),
      );
    } catch (e) {
      setSubError(e instanceof Error ? e.message : "Failed to fetch sub-devices");
    } finally {
      setSubLoading(false);
    }
  };

  const handleSubDeviceClick = (sub: SubDeviceItem) => {
    if (isDisabled) return;
    setSelectedSubDevice(sub);
    if (callback_id && onInteraction) {
      onInteraction(
        callback_id,
        { selected: { componentId: sub.id, name: sub.name, type: sub.type, machineId: sub.machineId } },
        block_id,
      );
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
    <div className="rounded-lg border bg-card p-4" role="region" aria-label={title ?? t.genui.ariaSubDeviceSelector}>
      {title && <h3 className="mb-2 text-sm font-medium">{title}</h3>}

      {treeLoading ? (
        <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">
          {t.genui.loadingOrgTree}
        </div>
      ) : treeError ? (
        <div className="flex h-80 items-center justify-center text-xs text-red-600">
          {t.genui.loadingFailed}: {treeError}
          <button type="button" className="ml-2 underline" onClick={fetchTree}>
            {t.genui.retry}
          </button>
        </div>
      ) : (
        <div className="flex gap-3" style={{ height: selectedParentDevice ? 500 : 320 }}>
          {/* Left: Org Tree */}
          <div className="w-1/2 overflow-hidden rounded-md border">
            <OrgTreePanel
              treeData={treeData}
              onSelectOrgNode={setSelectedOrgNode}
              selectedOrgId={selectedOrgNode?.id}
              disabled={isDisabled}
            />
          </div>

          {/* Right: Device list + Sub-device list */}
          <div className="flex w-1/2 flex-col gap-2">
            {/* Parent device list */}
            <div className="flex-1 overflow-y-auto rounded-md border p-2">
              {!selectedOrgNode ? (
                <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                  {t.genui.selectOrgNode}
                </div>
              ) : devices.length === 0 ? (
                <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                  {t.genui.noDevicesUnderNode}
                </div>
              ) : (
                <div className="space-y-1">
                  {devices.map((device) => (
                    <button
                      key={device.id}
                      type="button"
                      className={`w-full rounded px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted/50 disabled:opacity-50 ${
                        selectedParentDevice?.id === device.id ? "bg-primary/10 font-medium text-primary" : ""
                      }`}
                      onClick={() => handleParentDeviceClick(device)}
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

            {/* Sub-device list */}
            {selectedParentDevice && (
              <div className="flex-1 overflow-y-auto rounded-md border p-2">
                <div className="mb-1 text-xs text-muted-foreground">
                  {t.genui.subDeviceList}
                  {selectedParentDevice.type in DEVICE_TYPE_LABELS &&
                    `（${DEVICE_TYPE_LABELS[selectedParentDevice.type]}）`}
                </div>
                {subLoading ? (
                  <div className="flex h-24 items-center justify-center text-xs text-muted-foreground">
                    {t.genui.loadingSubDevices}
                  </div>
                ) : subError ? (
                  <div className="flex h-24 items-center justify-center text-xs text-red-600">
                    {t.genui.loadingFailed}: {subError}
                    <button
                      type="button"
                      className="ml-2 underline"
                      onClick={() => handleParentDeviceClick(selectedParentDevice)}
                    >
                      {t.genui.retry}
                    </button>
                  </div>
                ) : filteredSubDevices.length === 0 ? (
                  <div className="flex h-24 items-center justify-center text-xs text-muted-foreground">
                    {t.genui.noSubDevices}
                  </div>
                ) : (
                  <div className="space-y-1">
                    {filteredSubDevices.map((sub) => (
                      <button
                        key={sub.id}
                        type="button"
                        className={`w-full rounded px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted/50 disabled:opacity-50 ${
                          selectedSubDevice?.id === sub.id ? "bg-primary/10 font-medium text-primary" : ""
                        }`}
                        onClick={() => handleSubDeviceClick(sub)}
                        disabled={isDisabled}
                      >
                        {sub.name}
                      </button>
                    ))}
                  </div>
                )}
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
