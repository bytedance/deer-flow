import { describe, expect, test, vi } from "vitest";

import { viewerDraggers } from "@/lib/vsfx-viewer/runtime/Draggers";
import { Viewer } from "@/lib/vsfx-viewer/runtime/Viewer";

const APPROVED_COMMANDS = [
  "measureLine",
  "setSelected",
  "getSelected",
  "clearSelected",
  "k3DViewSW",
  "k3DViewTop",
  "k3DViewBottom",
  "k3DViewLeft",
  "k3DViewRight",
  "k3DViewFront",
  "k3DViewBack",
  "zoomToSelected",
  "zoomToExtents",
  "hideSelected",
  "isolateSelected",
  "showAll",
  "explode",
  "collect",
  "resetView",
  "regenerateAll",
  "clearSlices",
  "planeViewX",
  "planeViewY",
  "planeViewZ",
] as const;

function createVisualizeBackend() {
  return {
    clearSelected: vi.fn(),
    clearSlices: vi.fn(),
    collect: vi.fn(),
    dispose: vi.fn(),
    explode: vi.fn(),
    getSelected: vi.fn(() => [101]),
    hideSelected: vi.fn(),
    isolateSelected: vi.fn(),
    k3DViewBack: vi.fn(),
    k3DViewBottom: vi.fn(),
    k3DViewFront: vi.fn(),
    k3DViewLeft: vi.fn(),
    k3DViewRight: vi.fn(),
    k3DViewSW: vi.fn(),
    k3DViewTop: vi.fn(),
    measureLine: vi.fn(),
    parseVsfx: vi.fn(),
    planeViewX: vi.fn(),
    planeViewY: vi.fn(),
    planeViewZ: vi.fn(),
    regenerateAll: vi.fn(),
    render: vi.fn(),
    resetView: vi.fn(),
    resize: vi.fn(),
    setSelected: vi.fn(),
    showAll: vi.fn(),
    syncView: vi.fn(),
    update: vi.fn(),
    zoomToExtents: vi.fn(),
    zoomToSelected: vi.fn(),
  };
}

function createInteractionBackend() {
  const backend = createVisualizeBackend() as ReturnType<typeof createVisualizeBackend> & {
    readonly activeView: {
      beginInteractivity: ReturnType<typeof vi.fn>;
      delete: ReturnType<typeof vi.fn>;
      endInteractivity: ReturnType<typeof vi.fn>;
      perspective: boolean;
      upVector: number[];
      viewFieldHeight: number;
      viewFieldWidth: number;
      viewPosition: number[];
      viewTarget: number[];
      vportRect: [number, number, number, number];
    };
    getActiveDevice: ReturnType<typeof vi.fn>;
    getActiveTvExtendedView: ReturnType<typeof vi.fn>;
    screenToWorld: ReturnType<typeof vi.fn>;
    setActiveDragger: ReturnType<typeof vi.fn>;
    setView: ReturnType<typeof vi.fn>;
    zoomAt: ReturnType<typeof vi.fn>;
  };
  const viewState = {
    perspective: true,
    upVector: [0, 1, 0],
    viewFieldHeight: 10,
    viewFieldWidth: 10,
    viewPosition: [0, 0, 10],
    viewTarget: [0, 0, 0],
    vportRect: [0, 0, 100, 100] as [number, number, number, number],
  };
  const beginInteractivity = vi.fn();
  const endInteractivity = vi.fn();
  const setView = vi.fn(
    (
      position: number[],
      target: number[],
      upVector: number[],
      viewFieldWidth: number,
      viewFieldHeight: number,
      perspective: boolean,
    ) => {
      viewState.viewPosition = [...position];
      viewState.viewTarget = [...target];
      viewState.upVector = [...upVector];
      viewState.viewFieldWidth = viewFieldWidth;
      viewState.viewFieldHeight = viewFieldHeight;
      viewState.perspective = perspective;
    },
  );

  Object.defineProperty(backend, "activeView", {
    configurable: true,
    get: () => ({
      beginInteractivity,
      delete: vi.fn(),
      endInteractivity,
      perspective: viewState.perspective,
      upVector: [...viewState.upVector],
      viewFieldHeight: viewState.viewFieldHeight,
      viewFieldWidth: viewState.viewFieldWidth,
      viewPosition: [...viewState.viewPosition],
      viewTarget: [...viewState.viewTarget],
      vportRect: [...viewState.vportRect] as [number, number, number, number],
    }),
  });

  backend.getActiveDevice = vi.fn(() => ({
    delete: vi.fn(),
    invalidate: vi.fn(),
  }));
  backend.getActiveTvExtendedView = vi.fn(() => ({
    delete: vi.fn(),
    setView,
  }));
  backend.screenToWorld = vi.fn((x: number, y: number) => [x / 10, y / 10, 0]);
  backend.setActiveDragger = vi.fn();
  backend.setView = setView;
  backend.zoomAt = vi.fn();

  return backend;
}

function createSelectionSet(handles: string[]) {
  let index = 0;
  const entities = handles.map((handle) => ({
    delete: vi.fn(),
    getNativeDatabaseHandle: vi.fn(() => handle),
  }));
  const entityIds = entities.map((entity) => ({
    delete: vi.fn(),
    getType: vi.fn(() => 1),
    openObject: vi.fn(() => entity),
    openObjectAsInsert: vi.fn(() => entity),
  }));

  return {
    isNull: vi.fn(() => false),
    numItems: vi.fn(() => entityIds.length),
    getIterator: vi.fn(() => ({
      delete: vi.fn(),
      done: vi.fn(() => index >= entityIds.length),
      getEntity: vi.fn(() => entityIds[index]),
      step: vi.fn(() => {
        index += 1;
      }),
    })),
  };
}

function dispatchCanvasPointerEvent(
  target: HTMLCanvasElement,
  type: string,
  init: PointerEventInit & { offsetX?: number; offsetY?: number },
) {
  const event = new PointerEvent(type, {
    bubbles: true,
    isPrimary: true,
    pointerId: 1,
    pointerType: "mouse",
    ...init,
  });

  Object.defineProperties(event, {
    offsetX: {
      configurable: true,
      value: init.offsetX ?? init.clientX ?? 0,
    },
    offsetY: {
      configurable: true,
      value: init.offsetY ?? init.clientY ?? 0,
    },
  });

  target.dispatchEvent(event);
}

function dispatchCanvasWheelEvent(
  target: HTMLCanvasElement,
  init: WheelEventInit & { offsetX?: number; offsetY?: number },
) {
  const event = new WheelEvent("wheel", {
    bubbles: true,
    ...init,
  });

  Object.defineProperties(event, {
    offsetX: {
      configurable: true,
      value: init.offsetX ?? 0,
    },
    offsetY: {
      configurable: true,
      value: init.offsetY ?? 0,
    },
  });

  target.dispatchEvent(event);
}

describe("Viewer", () => {
  test("initializes and disposes cleanly without markup dependencies", async () => {
    const loadVisualizeLibrary = vi.fn(async () => ({ ready: true }));
    const backend = createVisualizeBackend();
    const createVisualizeViewer = vi.fn(() => backend);
    const container = document.createElement("div");

    const viewer = new Viewer({
      container,
      dependencies: {
        createVisualizeViewer,
        loadVisualizeLibrary,
      },
    });

    await viewer.initialize();

    expect(loadVisualizeLibrary).toHaveBeenCalledTimes(1);
    expect(createVisualizeViewer).toHaveBeenCalledWith({
      container,
      visualizeLibrary: { ready: true },
      wasmUrl: "/visualizejs/Visualize.js.wasm",
    });
    expect(viewer.getCommandNames()).toEqual(APPROVED_COMMANDS);
    expect(viewer.getDraggerNames()).toEqual([
      "pan",
      "orbit",
      "orbit-pan",
      "walk",
      "zoom",
      "zoom-wheel",
    ]);

    viewer.dispose();

    expect(backend.dispose).toHaveBeenCalledTimes(1);
  });

  test("opens binary vsfx data and executes the approved command subset", async () => {
    const backend = createVisualizeBackend();
    const viewer = new Viewer({
      container: document.createElement("div"),
      dependencies: {
        createVisualizeViewer: () => backend,
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });

    await viewer.initialize();

    const data = new Uint8Array([1, 2, 3]).buffer;
    await viewer.open({ data, filename: "sample.vsfx" });
    viewer.executeCommand("setSelected", [10, 20]);
    viewer.executeCommand("measureLine");
    viewer.executeCommand("k3DViewTop");
    viewer.executeCommand("zoomToSelected");
    viewer.executeCommand("planeViewX");
    viewer.executeCommand("collect");
    viewer.executeCommand("resetView");
    viewer.executeCommand("clearSlices");

    expect(backend.parseVsfx).toHaveBeenCalledWith(new Uint8Array(data));
    expect(backend.setSelected).toHaveBeenCalledWith([10, 20]);
    expect(backend.measureLine).toHaveBeenCalledTimes(1);
    expect(backend.k3DViewTop).toHaveBeenCalledTimes(1);
    expect(backend.zoomToSelected).toHaveBeenCalledTimes(1);
    expect(backend.planeViewX).toHaveBeenCalledTimes(1);
    expect(backend.collect).toHaveBeenCalledTimes(2);
    expect(backend.resetView).toHaveBeenCalledTimes(1);
    expect(backend.clearSlices).toHaveBeenCalledTimes(2);
  });

  test("initializes the real Visualize.js library contract through Viewer.create and getViewer", async () => {
    const backend = createVisualizeBackend();
    const createSpy = vi.fn();
    const resizeSpy = vi.fn();
    const syncViewSpy = vi.fn();
    const updateSpy = vi.fn();
    const renderSpy = vi.fn();
    const visualizeLibrary = {
      Viewer: {
        create: createSpy,
      },
      canvas: undefined as HTMLCanvasElement | undefined,
      getViewer: vi.fn(() => ({
        ...backend,
        render: renderSpy,
        resize: resizeSpy,
        syncView: syncViewSpy,
        update: updateSpy,
      })),
    };
    const canvas = document.createElement("canvas");
    Object.defineProperty(canvas, "clientWidth", {
      configurable: true,
      value: 200,
    });
    Object.defineProperty(canvas, "clientHeight", {
      configurable: true,
      value: 100,
    });
    vi.spyOn(window, "devicePixelRatio", "get").mockReturnValue(2);
    const viewer = new Viewer({
      container: canvas,
      dependencies: {
        loadVisualizeLibrary: async () => visualizeLibrary,
      },
    });

    await viewer.initialize();

    expect(visualizeLibrary.canvas).toBe(canvas);
    expect(createSpy).toHaveBeenCalledTimes(1);
    expect(canvas.style.width).toBe("100%");
    expect(canvas.style.height).toBe("100%");
    expect(canvas.width).toBe(400);
    expect(canvas.height).toBe(200);
    expect(visualizeLibrary.getViewer).toHaveBeenCalledTimes(1);
    expect(syncViewSpy).toHaveBeenCalledTimes(1);
    expect(resizeSpy).toHaveBeenCalledWith(0, 400, 200, 0);
    expect(updateSpy.mock.calls.length).toBeGreaterThanOrEqual(1);
    expect(renderSpy.mock.calls.length).toBeGreaterThanOrEqual(1);

    viewer.getVisualizeViewer()?.resize?.();

    expect(resizeSpy).toHaveBeenLastCalledWith(0, 400, 200, 0);
  });

  test("preserves the original Visualize viewer method binding through the canvas-aware adapter", async () => {
    const realViewer = {
      parseVsfx(this: unknown, _data: Uint8Array) {
        if (this !== realViewer) {
          throw new Error("lost real viewer binding");
        }
      },
      resize: vi.fn(),
    };
    const visualizeLibrary = {
      Viewer: {
        create: vi.fn(),
      },
      getViewer: vi.fn(() => realViewer),
    };
    const canvas = document.createElement("canvas");
    Object.defineProperty(canvas, "clientWidth", {
      configurable: true,
      value: 120,
    });
    Object.defineProperty(canvas, "clientHeight", {
      configurable: true,
      value: 60,
    });

    const viewer = new Viewer({
      container: canvas,
      dependencies: {
        loadVisualizeLibrary: async () => visualizeLibrary,
      },
    });

    await viewer.initialize();

    await expect(
      viewer.open({
        data: new Uint8Array([7, 8, 9]).buffer,
        filename: "binding.vsfx",
      }),
    ).resolves.toBeUndefined();
  });

  test("re-primes the real visualize backend after parse completes", async () => {
    const parseVsfx = vi.fn();
    const resizeSpy = vi.fn();
    const syncViewSpy = vi.fn();
    const updateSpy = vi.fn();
    const renderSpy = vi.fn();
    const realViewer = {
      parseVsfx,
      render: renderSpy,
      resize: resizeSpy,
      syncView: syncViewSpy,
      update: updateSpy,
    };
    const visualizeLibrary = {
      Viewer: {
        create: vi.fn(),
      },
      getViewer: vi.fn(() => realViewer),
    };
    const canvas = document.createElement("canvas");
    Object.defineProperty(canvas, "clientWidth", {
      configurable: true,
      value: 120,
    });
    Object.defineProperty(canvas, "clientHeight", {
      configurable: true,
      value: 60,
    });

    const viewer = new Viewer({
      container: canvas,
      dependencies: {
        loadVisualizeLibrary: async () => visualizeLibrary,
      },
    });

    await viewer.initialize();
    syncViewSpy.mockClear();
    resizeSpy.mockClear();
    updateSpy.mockClear();
    renderSpy.mockClear();

    await viewer.open({
      data: new Uint8Array([4, 5, 6]).buffer,
      filename: "primed.vsfx",
    });

    expect(parseVsfx).toHaveBeenCalledWith(new Uint8Array([4, 5, 6]));
    expect(syncViewSpy).toHaveBeenCalledTimes(1);
    expect(resizeSpy).toHaveBeenCalledTimes(1);
  });

  test("proxies update calls to the visualize backend so redraw-triggering commands take effect", async () => {
    const backend = createVisualizeBackend();
    const viewer = new Viewer({
      container: document.createElement("div"),
      dependencies: {
        createVisualizeViewer: () => backend,
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });

    const updateListener = vi.fn();
    viewer.on("update", updateListener);

    await viewer.initialize();
    backend.update.mockClear();

    viewer.update();

    expect(backend.update).toHaveBeenCalledTimes(1);
    expect(updateListener).toHaveBeenCalledWith(undefined);
  });

  test("forces a backend update and redraw after resize so the canvas stays valid", async () => {
    const backend = createVisualizeBackend();
    const canvas = document.createElement("canvas");
    Object.defineProperty(canvas, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        bottom: 220,
        height: 180,
        left: 0,
        right: 320,
        top: 40,
        width: 320,
        x: 0,
        y: 40,
        toJSON: () => undefined,
      }),
    });
    const viewer = new Viewer({
      container: canvas,
      dependencies: {
        createVisualizeViewer: () => backend,
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });
    const resizeListener = vi.fn();

    viewer.on("resize", resizeListener);
    await viewer.initialize();
    backend.resize.mockClear();
    backend.update.mockClear();
    backend.render.mockClear();

    viewer.resize();

    expect(backend.resize).toHaveBeenCalledTimes(1);
    expect(backend.update).toHaveBeenCalledTimes(1);
    expect(backend.render).not.toHaveBeenCalled();
    expect(resizeListener).toHaveBeenCalledWith({
      height: 180,
      width: 320,
    });
  });

  test("forwards pointer events from the canvas DOM into viewer listeners", async () => {
    const canvas = document.createElement("canvas");
    const viewer = new Viewer({
      container: canvas,
      dependencies: {
        createVisualizeViewer: () => createVisualizeBackend(),
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });
    const pointerDown = vi.fn();

    await viewer.initialize();
    (
      viewer as unknown as {
        on: (eventName: string, listener: (payload: unknown) => void) => () => void;
      }
    ).on("pointerdown", pointerDown);

    canvas.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0 }));

    expect(pointerDown).toHaveBeenCalledTimes(1);
  });

  test("reuses the active dragger when the same dragger is selected repeatedly", async () => {
    const provider = vi.fn(() => ({
      activate: vi.fn(),
      deactivate: vi.fn(),
      dispose: vi.fn(),
      id: "test-persistent",
    }));
    viewerDraggers.registerDragger("test-persistent", provider);

    const viewer = new Viewer({
      container: document.createElement("canvas"),
      dependencies: {
        createVisualizeViewer: () => createVisualizeBackend(),
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });

    await viewer.initialize();
    provider.mockClear();

    viewer.setActiveDragger("test-persistent");
    viewer.setActiveDragger("test-persistent");

    expect(provider).toHaveBeenCalledTimes(1);
  });

  test("initializes lifecycle-aware draggers when they become active", async () => {
    const activate = vi.fn();
    const dispose = vi.fn();
    const initialize = vi.fn();
    const provider = vi.fn(() => ({
      activate,
      deactivate: vi.fn(),
      dispose,
      id: "test-lifecycle",
      initialize,
    }));
    viewerDraggers.registerDragger("test-lifecycle", provider);

    const viewer = new Viewer({
      container: document.createElement("canvas"),
      dependencies: {
        createVisualizeViewer: () => createVisualizeBackend(),
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });

    await viewer.initialize();
    provider.mockClear();
    activate.mockClear();
    initialize.mockClear();
    dispose.mockClear();

    viewer.setActiveDragger("test-lifecycle");
    viewer.dispose();

    expect(provider).toHaveBeenCalledTimes(1);
    expect(activate).toHaveBeenCalledTimes(1);
    expect(initialize).toHaveBeenCalledTimes(1);
    expect(dispose).toHaveBeenCalledTimes(1);
  });

  test("registers zoom-wheel and gesture helpers through viewer event subscriptions", async () => {
    const viewer = new Viewer({
      container: document.createElement("canvas"),
      dependencies: {
        createVisualizeViewer: () => createVisualizeBackend(),
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });
    const onSpy = vi.spyOn(viewer, "on");
    const offSpy = vi.spyOn(viewer, "off");

    await viewer.initialize();
    viewer.dispose();

    expect(onSpy).toHaveBeenCalledWith("wheel", expect.any(Function));
    expect(onSpy).toHaveBeenCalledWith("pointerdown", expect.any(Function));
    expect(offSpy).toHaveBeenCalledWith("wheel", expect.any(Function));
    expect(offSpy).toHaveBeenCalledWith("pointerdown", expect.any(Function));
  });

  test("zoom wheel converts wheel input into backend zoomAt calls", async () => {
    const backend = createInteractionBackend();
    const canvas = document.createElement("canvas");
    vi.spyOn(window, "devicePixelRatio", "get").mockReturnValue(1);
    const viewer = new Viewer({
      container: canvas,
      dependencies: {
        createVisualizeViewer: () => backend,
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });

    await viewer.initialize();
    backend.zoomAt.mockClear();

    dispatchCanvasWheelEvent(canvas, { deltaY: -120, offsetX: 12, offsetY: 18 });

    expect(backend.zoomAt).toHaveBeenCalledTimes(1);
    expect(backend.zoomAt).toHaveBeenCalledWith(expect.any(Number), 12, 18);
  });

  test("orbit-pan maps left button drag to orbit and middle button drag to pan", async () => {
    const backend = createInteractionBackend();
    const canvas = document.createElement("canvas");
    canvas.setPointerCapture = vi.fn();
    canvas.releasePointerCapture = vi.fn();

    const viewer = new Viewer({
      container: canvas,
      dependencies: {
        createVisualizeViewer: () => backend,
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });

    await viewer.initialize();
    viewer.setActiveDragger("orbit-pan");
    backend.setView.mockClear();
    backend.screenToWorld.mockClear();

    dispatchCanvasPointerEvent(canvas, "pointerdown", {
      button: 0,
      clientX: 10,
      clientY: 10,
      offsetX: 10,
      offsetY: 10,
    });
    dispatchCanvasPointerEvent(canvas, "pointermove", {
      button: 0,
      clientX: 24,
      clientY: 26,
      offsetX: 24,
      offsetY: 26,
    });
    dispatchCanvasPointerEvent(canvas, "pointerup", {
      button: 0,
      clientX: 24,
      clientY: 26,
      offsetX: 24,
      offsetY: 26,
    });

    expect(backend.setView).toHaveBeenCalled();
    expect(backend.screenToWorld).not.toHaveBeenCalled();

    backend.setView.mockClear();
    backend.screenToWorld.mockClear();

    dispatchCanvasPointerEvent(canvas, "pointerdown", {
      button: 1,
      clientX: 18,
      clientY: 18,
      offsetX: 18,
      offsetY: 18,
    });
    dispatchCanvasPointerEvent(canvas, "pointermove", {
      button: 1,
      clientX: 28,
      clientY: 30,
      offsetX: 28,
      offsetY: 30,
    });
    dispatchCanvasPointerEvent(canvas, "pointerup", {
      button: 1,
      clientX: 28,
      clientY: 30,
      offsetX: 28,
      offsetY: 30,
    });

    expect(backend.screenToWorld).toHaveBeenCalled();
    expect(backend.setView).toHaveBeenCalled();
  });

  test("hideSelected clears the runtime selection after hiding the current handles", async () => {
    const backend = createVisualizeBackend();
    backend.getSelected.mockReturnValue([101, 202]);
    const viewer = new Viewer({
      container: document.createElement("canvas"),
      dependencies: {
        createVisualizeViewer: () => backend,
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });
    const hideListener = vi.fn();
    const selectListener = vi.fn();

    viewer.on("hide", hideListener);
    viewer.on("select", selectListener);
    await viewer.initialize();
    hideListener.mockClear();
    selectListener.mockClear();

    viewer.executeCommand("hideSelected");

    expect(backend.hideSelected).toHaveBeenCalledTimes(1);
    expect(hideListener).toHaveBeenCalledWith([101, 202]);
    expect(selectListener).toHaveBeenLastCalledWith([]);
  });

  test("normalizes visualize selection sets into handle arrays before emitting selection", async () => {
    const backend = createVisualizeBackend();
    const selectionSet = createSelectionSet(["A1", "B2"]);
    backend.getSelected.mockReturnValue(selectionSet);
    const canvas = document.createElement("canvas");
    const viewer = new Viewer({
      container: canvas,
      dependencies: {
        createVisualizeViewer: () => backend,
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });
    const selectListener = vi.fn();

    await viewer.initialize();
    viewer.on("select", selectListener);

    backend.select = vi.fn();
    backend.unselect = vi.fn();

    const clickEvent = new MouseEvent("click", { bubbles: true });
    Object.defineProperties(clickEvent, {
      offsetX: {
        configurable: true,
        value: 16,
      },
      offsetY: {
        configurable: true,
        value: 24,
      },
    });

    dispatchCanvasPointerEvent(canvas, "pointerdown", {
      button: 0,
      clientX: 16,
      clientY: 24,
      offsetX: 16,
      offsetY: 24,
    });
    canvas.dispatchEvent(clickEvent);

    expect(selectListener).toHaveBeenLastCalledWith(["A1", "B2"]);
  });

  test("clearSlices restores the default SW view after removing plane cuts", async () => {
    const backend = createVisualizeBackend();
    const viewer = new Viewer({
      container: document.createElement("canvas"),
      dependencies: {
        createVisualizeViewer: () => backend,
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });

    await viewer.initialize();
    backend.clearSlices.mockClear();
    backend.k3DViewSW.mockClear();

    viewer.executeCommand("clearSlices");

    expect(backend.clearSlices).toHaveBeenCalledTimes(1);
    expect(backend.k3DViewSW).toHaveBeenCalledTimes(1);
  });

  test("resetView restores the scene and camera to the SW baseline", async () => {
    const backend = createVisualizeBackend();
    const viewer = new Viewer({
      container: document.createElement("canvas"),
      dependencies: {
        createVisualizeViewer: () => backend,
        loadVisualizeLibrary: async () => ({ ready: true }),
      },
    });

    await viewer.initialize();
    backend.clearSlices.mockClear();
    backend.clearSelected.mockClear();
    backend.showAll.mockClear();
    backend.collect.mockClear();
    backend.zoomToExtents.mockClear();
    backend.k3DViewSW.mockClear();
    backend.resetView.mockClear();

    viewer.executeCommand("resetView");

    expect(backend.clearSlices).toHaveBeenCalledTimes(1);
    expect(backend.clearSelected).toHaveBeenCalledTimes(1);
    expect(backend.showAll).toHaveBeenCalledTimes(1);
    expect(backend.collect).toHaveBeenCalledTimes(1);
    expect(backend.zoomToExtents).toHaveBeenCalledTimes(1);
    expect(backend.k3DViewSW).toHaveBeenCalledTimes(2);
    expect(backend.resetView).toHaveBeenCalledTimes(1);
  });
});
