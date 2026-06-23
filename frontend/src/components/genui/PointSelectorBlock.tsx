"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import type { InteractionState } from "@/core/genui/store";
import { useI18n } from "@/core/i18n/hooks";

import { collectDevices } from "./device-selector-utils";
import type { DeviceQueryParams, OrgTreeNode } from "./device-selector-types";
import OrgTreePanel from "./OrgTreePanel";

interface PointSelectorBlockProps {
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

interface PointInfo {
  id: string;
  name: string;
  machineId: string;
  parentId: string;
  type: number;
  moniType: number;
  displayOrder: number;
  componentName: string;
  sampleName: string;
  samplingPointName: string;
  corrosionFlag: number;
}

interface SelectedPoint {
  id: string;
  name: string;
  machineId: string;
  type: number;
  componentName: string;
}

/**
 * Pre-process raw JSON text to convert integer literals with 16+ digits into
 * string literals, preventing precision loss for Java Long IDs that exceed
 * Number.MAX_SAFE_INTEGER (9007199254740991).
 */
function safeJsonParse<T = unknown>(text: string): T {
  const safe = text.replace(
    /(?<=[\[{,]\s*)(-?\d{16,})(?=\s*[,\]}])/g,
    '"$1"',
  );
  return JSON.parse(safe) as T;
}

function getBaseUrl(): string {
  if (typeof window !== "undefined") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

export default function PointSelectorBlock({ block }: PointSelectorBlockProps) {
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
  const [treeLoading, setTreeLoading] = useState(true);
  const [treeError, setTreeError] = useState<string | null>(null);
  const [selectedOrgNode, setSelectedOrgNode] = useState<OrgTreeNode | null>(null);
  const [selectedDevice, setSelectedDevice] = useState<OrgTreeNode | null>(null);

  const [points, setPoints] = useState<PointInfo[]>([]);
  const [pointsLoading, setPointsLoading] = useState(false);
  const [pointsError, setPointsError] = useState<string | null>(null);
  const [selectedPoint, setSelectedPoint] = useState<SelectedPoint | null>(null);

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

  /**
   * Look up the original (unfiltered) node from treeData by id.
   *
   * The OrgTreePanel search (`filterTree`) returns shallow-copied nodes whose
   * `children` are already filtered to the search term. If we pass that
   * filtered copy to `collectDevices`, any device child that doesn't match
   * the search keyword is silently dropped — causing "no devices under this
   * org node" even though devices exist in the real tree.
   */
  const findNodeById = useCallback(
    (id: string): OrgTreeNode | null => {
      const walk = (nodes: OrgTreeNode[]): OrgTreeNode | null => {
        for (const n of nodes) {
          if (n.id === id) return n;
          if (n.children) {
            const found = walk(n.children);
            if (found) return found;
          }
        }
        return null;
      };
      return walk(treeData);
    },
    [treeData],
  );

  const devices = useMemo(() => {
    if (!selectedOrgNode) return [];
    const originalNode = findNodeById(selectedOrgNode.id) ?? selectedOrgNode;
    return collectDevices(originalNode, filterDeviceType);
  }, [selectedOrgNode, filterDeviceType, findNodeById]);

  const sortedPoints = useMemo(() => {
    return [...points].sort((a, b) => (a.displayOrder ?? 0) - (b.displayOrder ?? 0));
  }, [points]);

  const handleDeviceClick = async (device: OrgTreeNode) => {
    if (isDisabled) return;
    setSelectedDevice(device);
    setSelectedPoint(null);
    setPointsError(null);
    setPointsLoading(true);
    try {
      const baseUrl = getBaseUrl();
      const res = await fetch(`${baseUrl}/api/point/list?machineIds=${device.id}`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const text = await res.text();
      const data = safeJsonParse<unknown[]>(text);
      const list = Array.isArray(data) ? (data as Record<string, unknown>[]) : [];
      setPoints(
        list.map((item) => ({
          id: String(item.id),
          name: (item.name as string) ?? "",
          machineId: String(item.machineId),
          parentId: String(item.parentId ?? 0),
          type: Number(item.type ?? 0),
          moniType: Number(item.moniType ?? 0),
          displayOrder: Number(item.displayOrder ?? 0),
          componentName: (item.componentName as string) ?? "",
          sampleName: (item.sampleName as string) ?? "",
          samplingPointName: (item.samplingPointName as string) ?? "",
          corrosionFlag: Number(item.corrosionFlag ?? 0),
        })),
      );
    } catch (e) {
      setPointsError(e instanceof Error ? e.message : "Failed to fetch points");
    } finally {
      setPointsLoading(false);
    }
  };

  const handlePointClick = (point: PointInfo) => {
    if (isDisabled) return;
    const selected: SelectedPoint = {
      id: point.id,
      name: point.name,
      machineId: point.machineId,
      type: point.type,
      componentName: point.componentName,
    };
    setSelectedPoint(selected);
    if (callback_id && onInteraction) {
      onInteraction(
        callback_id,
        {
          selected,
          device: selectedDevice
            ? { id: selectedDevice.id, label: selectedDevice.label, type: selectedDevice.type }
            : null,
        },
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
    <div className="rounded-lg border bg-card p-4" role="region" aria-label={title ?? t.genui.ariaPointSelector}>
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
        <div className="flex gap-3" style={{ height: selectedDevice ? 500 : 320 }}>
          {/* Left: Org Tree */}
          <div className="w-1/2 overflow-hidden rounded-md border">
            <OrgTreePanel
              treeData={treeData}
              onSelectOrgNode={setSelectedOrgNode}
              selectedOrgId={selectedOrgNode?.id}
              disabled={isDisabled}
            />
          </div>

          {/* Right: Device list + Point list */}
          <div className="flex w-1/2 flex-col gap-2">
            {/* Device list */}
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

            {/* Point list */}
            {selectedDevice && (
              <div className="flex-1 overflow-y-auto rounded-md border p-2">
                <div className="mb-1 text-xs text-muted-foreground">
                  {t.genui.pointList}
                  {selectedDevice.type in DEVICE_TYPE_LABELS &&
                    `（${DEVICE_TYPE_LABELS[selectedDevice.type]} — ${selectedDevice.label}）`}
                </div>
                {pointsLoading ? (
                  <div className="flex h-24 items-center justify-center text-xs text-muted-foreground">
                    {t.genui.loadingPoints}
                  </div>
                ) : pointsError ? (
                  <div className="flex h-24 items-center justify-center text-xs text-red-600">
                    {t.genui.loadingFailed}: {pointsError}
                    <button
                      type="button"
                      className="ml-2 underline"
                      onClick={() => handleDeviceClick(selectedDevice)}
                    >
                      {t.genui.retry}
                    </button>
                  </div>
                ) : sortedPoints.length === 0 ? (
                  <div className="flex h-24 items-center justify-center text-xs text-muted-foreground">
                    {t.genui.noPoints}
                  </div>
                ) : (
                  <div className="space-y-1">
                    {sortedPoints.map((point) => (
                      <button
                        key={point.id}
                        type="button"
                        className={`w-full rounded px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted/50 disabled:opacity-50 ${
                          selectedPoint?.id === point.id ? "bg-primary/10 font-medium text-primary" : ""
                        }`}
                        onClick={() => handlePointClick(point)}
                        disabled={isDisabled}
                      >
                        {point.name}
                        {point.componentName && (
                          <span className="ml-1 text-muted-foreground">
                            ({point.componentName})
                          </span>
                        )}
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
