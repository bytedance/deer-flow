"use client";

import { useMemo, useState } from "react";

import type { InteractionState } from "@/core/genui/store";

import type { OrgTreeNode, SelectedDevice } from "./device-selector-types";
import OrgTreePanel from "./OrgTreePanel";

interface DeviceSelectorBlockProps {
  block: {
    block_id?: string;
    props: {
      title?: string;
      treeData: OrgTreeNode[];
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

export default function DeviceSelectorBlock({ block }: DeviceSelectorBlockProps) {
  const { block_id, props, callback_id, interactionState, onInteraction } = block;
  const { title, treeData } = props;

  const [selectedOrgNode, setSelectedOrgNode] = useState<OrgTreeNode | null>(null);
  const [selectedDevice, setSelectedDevice] = useState<SelectedDevice | null>(null);

  const isDisabled =
    interactionState?.status === "loading" ||
    interactionState?.status === "submitted" ||
    interactionState?.status === "expired" ||
    interactionState?.status === "readonly";

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

      {interactionState?.status === "error" && (
        <p className="mt-2 text-xs text-red-600" role="alert">{interactionState.error}</p>
      )}
    </div>
  );
}
