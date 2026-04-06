import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { ensureVisualizeScript, loadVisualizeLibrary } from "./utils";

async function flushMicrotasks() {
  await Promise.resolve();
  await Promise.resolve();
}

function createFactory<T extends VisualizeLibraryInstance>(
  library: T,
  script: HTMLScriptElement,
): VisualizeLibraryFactory {
  const factory: VisualizeLibraryFactory = () => library;
  factory.script = script;
  return vi.fn(factory);
}

describe("loadVisualizeLibrary", () => {
  const originalFactory = window.getVisualizeLibInst;

  beforeEach(() => {
    const existingScript = document.querySelector('script[data-visualize-script="true"]');
    existingScript?.remove();
  });

  afterEach(() => {
    window.getVisualizeLibInst = originalFactory;
    vi.restoreAllMocks();
    const existingScript = document.querySelector('script[data-visualize-script="true"]');
    existingScript?.remove();
  });

  test("waits for the Visualize postRun hook before resolving the library", async () => {
    const script = document.createElement("script");
    script.dataset.visualizeScript = "true";
    script.dataset.loaded = "true";
    script.src = "/visualizejs/Visualize.js";
    document.head.append(script);

    const library = {
      postRun: [] as Array<() => void>,
    };

    const factory = createFactory(library, script);
    window.getVisualizeLibInst = factory;

    let resolved = false;
    const loadPromise = loadVisualizeLibrary().then(() => {
      resolved = true;
    });

    await flushMicrotasks();

    expect(resolved).toBe(false);
    expect(library.postRun).toHaveLength(1);

    const postRunCallback = library.postRun[0];

    expect(postRunCallback).toBeDefined();
    postRunCallback?.();
    await loadPromise;

    expect(resolved).toBe(true);
  });

  test("does not resolve early just because the module exposes Viewer/getViewer shapes", async () => {
    const script = document.createElement("script");
    script.dataset.visualizeScript = "true";
    script.dataset.loaded = "true";
    script.src = "/visualizejs/Visualize.js";
    document.head.append(script);

    const library = {
      Viewer: {
        create: vi.fn(),
      },
      getViewer: vi.fn(),
      postRun: [] as Array<() => void>,
    };

    const factory = createFactory(library, script);
    window.getVisualizeLibInst = factory;

    let resolved = false;
    const loadPromise = loadVisualizeLibrary().then(() => {
      resolved = true;
    });

    await flushMicrotasks();

    expect(resolved).toBe(false);
    expect(library.postRun).toHaveLength(1);

    library.postRun[0]?.();
    await loadPromise;

    expect(resolved).toBe(true);
  });

  test("does not resolve early when the module already exposes function-shaped Viewer/getViewer APIs", async () => {
    const script = document.createElement("script");
    script.dataset.visualizeScript = "true";
    script.dataset.loaded = "true";
    script.src = "/visualizejs/Visualize.js";
    document.head.append(script);

    const library = {
      Viewer: vi.fn(),
      getViewer: vi.fn(),
      postRun: [] as Array<() => void>,
    };

    const factory = createFactory(library, script);
    window.getVisualizeLibInst = factory;

    let resolved = false;
    const loadPromise = loadVisualizeLibrary().then(() => {
      resolved = true;
    });

    await flushMicrotasks();

    expect(resolved).toBe(false);
    expect(library.postRun).toHaveLength(1);

    library.postRun[0]?.();
    await loadPromise;

    expect(resolved).toBe(true);
  });

  test("passes cad-web style factory options including TOTAL_MEMORY and loadWasmError", async () => {
    const script = document.createElement("script");
    script.dataset.visualizeScript = "true";
    script.dataset.loaded = "true";
    script.src = "/visualizejs/Visualize.js";
    document.body.append(script);

    const library = {
      loadWasmError: undefined,
      postRun: [] as Array<() => void>,
    };

    const factory = createFactory(library, script);
    window.getVisualizeLibInst = factory;

    const loadPromise = loadVisualizeLibrary({ wasmUrl: "/custom.wasm" });

    await flushMicrotasks();

    expect(factory).toHaveBeenCalledWith({
      TOTAL_MEMORY: 134217728,
      onprogress: expect.any(Function),
      urlMemFile: "/custom.wasm",
    });
    expect(typeof library.loadWasmError).toBe("function");

    library.postRun[0]?.();
    await expect(loadPromise).resolves.toBe(library);
  });

  test("reuses the existing factory script when the script url matches", async () => {
    const existingScript = document.createElement("script");
    existingScript.dataset.loaded = "true";
    existingScript.src = "/visualizejs/Visualize.js";
    const factory = createFactory({ postRun: [] }, existingScript);
    window.getVisualizeLibInst = factory;

    await ensureVisualizeScript("/visualizejs/Visualize.js");

    expect(document.querySelectorAll('script[data-visualize-script="true"]')).toHaveLength(0);
  });
});
