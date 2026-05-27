"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import type { InteractionState } from "@/core/genui/store";
import { useI18n } from "@/core/i18n/hooks";

import type { DeviceQueryParams, OrgTreeNode, SelectedDevice } from "./device-selector-types";
import { collectDevices } from "./device-selector-utils";
import OrgTreePanel from "./OrgTreePanel";

interface DeviceSelectorBlockProps {
  block: {
    block_id?: string;
    props: {
      title?: string;
      queryParams?: DeviceQueryParams;
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

export default function DeviceSelectorBlock({ block }: DeviceSelectorBlockProps) {
  const { t } = useI18n();
  const { block_id, props, callback_id, interactionState, onInteraction } = block;

  const DEVICE_TYPE_LABELS: Record<number, string> = {
    1: t.genui.deviceTypeRotating,
    4: t.genui.deviceTypePump,
    6: t.genui.deviceTypeStatic,
    9: t.genui.deviceTypeReciprocating,
  };
  const { title, queryParams, filterDeviceType } = props;
  const { user } = useAuth();

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
    <div className="rounded-lg border bg-card p-4" role="region" aria-label={title ?? t.genui.ariaDeviceSelector}>
      {title && <h3 className="mb-2 text-sm font-medium">{title}</h3>}

      {loading ? (
        <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">
          {t.genui.loadingOrgTree}
        </div>
      ) : fetchError ? (
        <div className="flex h-80 items-center justify-center text-xs text-red-600">
          {t.genui.loadingFailed}: {fetchError}
          <button
            type="button"
            className="ml-2 underline"
            onClick={fetchTree}
          >
            {t.genui.retry}
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
