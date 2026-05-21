import { describe, expect, it } from "vitest";

import { collectDevices } from "@/components/genui/device-selector-utils";
import type { OrgTreeNode } from "@/components/genui/device-selector-types";

function org(id: string, label: string, children: OrgTreeNode[] = []): OrgTreeNode {
  return { id, label, type: 10, path: `/${label}`, parentId: "0", children };
}

function device(id: string, label: string, type: number, displayOrder = 0): OrgTreeNode {
  return { id, label, type, path: `/${label}`, parentId: "p", displayOrder };
}

describe("collectDevices", () => {
  it("returns all devices under an org node when no filterDeviceType is given", () => {
    const node = org("o1", "A区", [
      device("d1", "P-1", 4),
      device("d2", "RM-1", 1),
      device("d3", "SE-1", 6),
    ]);
    const result = collectDevices(node);
    expect(result.map((d) => d.id).sort()).toEqual(["d1", "d2", "d3"]);
  });

  it("filters strictly by filterDeviceType — static_equipment selects only type=6", () => {
    const node = org("o1", "厂区", [
      device("d1", "P-1", 4),
      device("d2", "RM-1", 1),
      device("d3", "SE-1", 6),
      device("d4", "SE-2", 6),
    ]);
    const result = collectDevices(node, 6);
    expect(result.map((d) => d.id).sort()).toEqual(["d3", "d4"]);
    expect(result.every((d) => d.type === 6)).toBe(true);
  });

  it("never includes type=1 (rotating) when filterDeviceType=6 (static)", () => {
    const node = org("o1", "厂区", [
      device("d1", "RM-1", 1),
      device("d2", "RM-2", 1),
    ]);
    const result = collectDevices(node, 6);
    expect(result).toEqual([]);
  });

  it("walks org sub-trees but never re-classifies their devices", () => {
    const node = org("root", "总厂", [
      org("a", "A区", [
        device("d1", "RM-1", 1),
        device("d2", "SE-1", 6),
      ]),
      org("b", "B区", [
        device("d3", "P-1", 4),
        device("d4", "SE-2", 6),
      ]),
    ]);
    const result = collectDevices(node, 6);
    expect(result.map((d) => d.id).sort()).toEqual(["d2", "d4"]);
  });

  it("does recurse into device children but applies filter to all descendants", () => {
    // Real InS trees occasionally nest org sub-groups under device nodes.
    // The walker must descend through device children to reach them, but
    // still filters every descendant by filterDeviceType.
    const subGroup = { id: "sg", label: "子区域", type: 10, path: "/d1/sg", parentId: "d1", children: [
      { id: "d2", label: "SE-2", type: 6, path: "/d1/sg/SE-2", parentId: "sg" },
    ]};
    const node = org("o1", "A区", [
      { id: "d1", label: "SE-1", type: 6, path: "/SE-1", parentId: "o1", children: [subGroup] },
    ]);
    const result = collectDevices(node, 6);
    expect(result.map((d) => d.id).sort()).toEqual(["d1", "d2"]);
  });

  it("sorts devices by displayOrder ascending", () => {
    const node = org("o1", "A区", [
      device("d1", "C", 6, 3),
      device("d2", "A", 6, 1),
      device("d3", "B", 6, 2),
    ]);
    const result = collectDevices(node, 6);
    expect(result.map((d) => d.id)).toEqual(["d2", "d3", "d1"]);
  });
});
