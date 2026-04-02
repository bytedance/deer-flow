import type { VsfxContextValue } from "./context";

type VsfxRuntimeViewer = VsfxContextValue["state"]["viewer"] & {
  setActiveDragger?: (name: string) => void;
};

export type VsfxToolbarDraggerName = "pan" | "orbit" | "orbit-pan" | "walk" | "zoom";

export type VsfxToolbarCommandName =
  | "k3DViewBack"
  | "k3DViewBottom"
  | "k3DViewFront"
  | "k3DViewLeft"
  | "k3DViewRight"
  | "k3DViewSW"
  | "k3DViewTop"
  | "clearSelected"
  | "clearSlices"
  | "collect"
  | "explode"
  | "hideSelected"
  | "isolateSelected"
  | "measureLine"
  | "planeViewX"
  | "planeViewY"
  | "planeViewZ"
  | "regenerateAll"
  | "resetView"
  | "showAll"
  | "zoomToExtents"
  | "zoomToSelected";

export type VsfxToolbarItem = {
  commandName?: VsfxToolbarCommandName;
  draggerName?: VsfxToolbarDraggerName;
  id: string;
  label: string;
  selectionDependent?: boolean;
  run: (context: VsfxContextValue) => void;
};

export type VsfxToolbarGroup = {
  id: string;
  items: VsfxToolbarItem[];
  label: string;
  type: "buttons" | "toggles";
};

export const VSFX_TOOLBAR_GROUPS: VsfxToolbarGroup[] = [
  {
    id: "navigation",
    label: "Navigation",
    type: "toggles",
    items: [
      createDraggerItem("pan", "Pan"),
      createDraggerItem("orbit", "Orbit"),
      createDraggerItem("orbit-pan", "Orbit/Pan"),
      createDraggerItem("walk", "Walk"),
      createDraggerItem("zoom", "Zoom"),
    ],
  },
  {
    id: "measure",
    label: "Measure",
    type: "buttons",
    items: [
      createCommandItem("measureLine", "Measure line", ({ state }) => {
        state.viewer?.executeCommand("measureLine");
      }),
    ],
  },
  {
    id: "views",
    label: "3D views",
    type: "buttons",
    items: [
      createCommandItem("k3DViewSW", "SW", ({ state }) => {
        state.viewer?.executeCommand("k3DViewSW");
      }),
      createCommandItem("k3DViewTop", "Top", ({ state }) => {
        state.viewer?.executeCommand("k3DViewTop");
      }),
      createCommandItem("k3DViewBottom", "Bottom", ({ state }) => {
        state.viewer?.executeCommand("k3DViewBottom");
      }),
      createCommandItem("k3DViewLeft", "Left", ({ state }) => {
        state.viewer?.executeCommand("k3DViewLeft");
      }),
      createCommandItem("k3DViewRight", "Right", ({ state }) => {
        state.viewer?.executeCommand("k3DViewRight");
      }),
      createCommandItem("k3DViewFront", "Front", ({ state }) => {
        state.viewer?.executeCommand("k3DViewFront");
      }),
      createCommandItem("k3DViewBack", "Back", ({ state }) => {
        state.viewer?.executeCommand("k3DViewBack");
      }),
      createCommandItem("zoomToExtents", "Fit", ({ actions }) => {
        actions.zoomToExtents();
      }),
    ],
  },
  {
    id: "cuts",
    label: "Cuts",
    type: "buttons",
    items: [
      createCommandItem("planeViewX", "X Slice", ({ state }) => {
        state.viewer?.executeCommand("planeViewX");
      }),
      createCommandItem("planeViewY", "Y Slice", ({ state }) => {
        state.viewer?.executeCommand("planeViewY");
      }),
      createCommandItem("planeViewZ", "Z Slice", ({ state }) => {
        state.viewer?.executeCommand("planeViewZ");
      }),
      createCommandItem("clearSlices", "Clear cuts", ({ actions }) => {
        actions.clearSlices();
      }),
    ],
  },
  {
    id: "selection",
    label: "Selection",
    type: "buttons",
    items: [
      createCommandItem(
        "zoomToSelected",
        "Fit selected",
        ({ actions }) => {
          actions.zoomToSelected();
        },
        { selectionDependent: true },
      ),
      createCommandItem(
        "isolateSelected",
        "Isolate",
        ({ actions }) => {
          actions.isolateSelected();
        },
        { selectionDependent: true },
      ),
      createCommandItem(
        "hideSelected",
        "Hide",
        ({ actions }) => {
          actions.hideSelected();
        },
        { selectionDependent: true },
      ),
      createCommandItem("showAll", "Show all", ({ actions }) => {
        actions.showAll();
      }),
      createCommandItem(
        "clearSelected",
        "Unselect",
        ({ actions }) => {
          actions.clearSelection();
        },
        { selectionDependent: true },
      ),
    ],
  },
  {
    id: "model",
    label: "Model",
    type: "buttons",
    items: [
      createCommandItem("explode", "Explode", ({ state }) => {
        state.viewer?.executeCommand("explode");
      }),
      createCommandItem("collect", "Collect", ({ state }) => {
        state.viewer?.executeCommand("collect");
      }),
      createCommandItem("regenerateAll", "Refresh", ({ actions }) => {
        actions.regenerateAll();
      }),
      createCommandItem("resetView", "Reset", ({ actions }) => {
        actions.resetView();
      }),
    ],
  },
];

export const VSFX_TOOLBAR_FORBIDDEN_LABELS = ["Markup", "Preview", "Save", "Viewpoints"];

export function getVsfxToolbarDraggerValue(viewer: VsfxContextValue["state"]["viewer"]) {
  const runtimeViewer = viewer as VsfxRuntimeViewer | null;

  return runtimeViewer?.setActiveDragger ? "orbit-pan" : undefined;
}

function createCommandItem(
  commandName: VsfxToolbarCommandName,
  label: string,
  run: VsfxToolbarItem["run"],
  options: Pick<VsfxToolbarItem, "selectionDependent"> = {},
): VsfxToolbarItem {
  return {
    commandName,
    id: commandName,
    label,
    run,
    selectionDependent: options.selectionDependent,
  };
}

function createDraggerItem(
  draggerName: VsfxToolbarDraggerName,
  label: string,
): VsfxToolbarItem {
  return {
    draggerName,
    id: draggerName,
    label,
    run: ({ state }) => {
      const runtimeViewer = state.viewer as VsfxRuntimeViewer | null;
      runtimeViewer?.setActiveDragger?.(draggerName);
    },
  };
}
