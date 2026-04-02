import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { loadVisualizeLibrary } from "./utils";

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

    window.getVisualizeLibInst = vi.fn(() => library);

    let resolved = false;
    const loadPromise = loadVisualizeLibrary().then(() => {
      resolved = true;
    });

    await Promise.resolve();

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

    window.getVisualizeLibInst = vi.fn(() => library);

    let resolved = false;
    const loadPromise = loadVisualizeLibrary().then(() => {
      resolved = true;
    });

    await Promise.resolve();

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

    window.getVisualizeLibInst = vi.fn(() => library);

    let resolved = false;
    const loadPromise = loadVisualizeLibrary().then(() => {
      resolved = true;
    });

    await Promise.resolve();

    expect(resolved).toBe(false);
    expect(library.postRun).toHaveLength(1);

    library.postRun[0]?.();
    await loadPromise;

    expect(resolved).toBe(true);
  });
});
