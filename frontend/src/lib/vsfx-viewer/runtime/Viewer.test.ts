import { describe, expect, test, vi } from "vitest";

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
});
