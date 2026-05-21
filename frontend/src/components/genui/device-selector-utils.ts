import type { OrgTreeNode } from "./device-selector-types";

/**
 * Flatten devices from an org tree node.
 *
 * Filtering invariants:
 * - Devices = nodes with `type < 10` (anything ≥ 10 is an org level).
 * - When `filterDeviceType` is provided, only devices whose `type` strictly
 *   equals it are returned — never approximate, never via tree position. This
 *   is what makes "静设备 (6)" reject rotating-machinery (1) devices even if
 *   the backend returns a mixed tree.
 * - Recursion descends into ALL children (including device children). Real
 *   InS trees occasionally nest org nodes under device nodes; skipping
 *   device children would miss those sub-trees.
 * - Output is sorted by `displayOrder` ascending; ties keep insertion order.
 */
export function collectDevices(node: OrgTreeNode, filterDeviceType?: number): OrgTreeNode[] {
  const devices: OrgTreeNode[] = [];
  if (node.children) {
    for (const child of node.children) {
      if (child.type < 10) {
        if (filterDeviceType == null || child.type === filterDeviceType) {
          devices.push(child);
        }
      }
      if (child.children) {
        devices.push(...collectDevices(child, filterDeviceType));
      }
    }
  }
  return devices.sort((a, b) => (a.displayOrder ?? 0) - (b.displayOrder ?? 0));
}
