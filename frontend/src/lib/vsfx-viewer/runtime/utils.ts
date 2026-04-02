import { getVisualizeAssetPaths } from "./asset-paths";

export type VisualizeProgressState = {
  loaded: number;
  percent: number;
  total: number;
};

export type LoadVisualizeLibraryOptions = {
  onProgress?: (state: VisualizeProgressState) => void;
  scriptUrl?: string;
  wasmUrl?: string;
};

export async function ensureVisualizeScript(scriptUrl = getVisualizeAssetPaths().scriptUrl) {
  if (typeof window === "undefined" || typeof document === "undefined") {
    throw new Error("Visualize.js can only be loaded in a browser environment");
  }

  if (window.getVisualizeLibInst) {
    return;
  }

  const existing = document.querySelector<HTMLScriptElement>(
    `script[data-visualize-script="true"][src="${scriptUrl}"]`,
  );

  if (existing) {
    await waitForScript(existing);
    return;
  }

  const script = document.createElement("script");
  script.async = true;
  script.dataset.visualizeScript = "true";
  script.src = scriptUrl;
  document.head.append(script);

  await waitForScript(script);
}

export async function loadVisualizeLibrary({
  onProgress,
  scriptUrl = getVisualizeAssetPaths().scriptUrl,
  wasmUrl = getVisualizeAssetPaths().wasmUrl,
}: LoadVisualizeLibraryOptions = {}) {
  await ensureVisualizeScript(scriptUrl);

  const factory = window.getVisualizeLibInst;

  if (!factory) {
    throw new Error("Visualize.js factory was not found on window.getVisualizeLibInst");
  }

  return await new Promise<unknown>((resolve) => {
    const library = factory({
      onprogress: (event) => {
        onProgress?.(toVisualizeProgressState(event));
      },
      urlMemFile: wasmUrl,
    });

    if (Array.isArray(library.postRun)) {
      library.postRun.push(() => {
        resolve(library);
      });
      return;
    }

    resolve(library);
  });
}

export function toVisualizeProgressState(
  event: Pick<ProgressEvent<EventTarget>, "loaded" | "total">,
): VisualizeProgressState {
  const loaded = typeof event.loaded === "number" ? event.loaded : 0;
  const total = typeof event.total === "number" ? event.total : 0;
  const percent = total > 0 ? clampPercent((loaded / total) * 100) : 0;

  return {
    loaded,
    percent,
    total,
  };
}

function clampPercent(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.min(100, Math.max(0, value));
}

function waitForScript(script: HTMLScriptElement) {
  if (script.dataset.loaded === "true") {
    return Promise.resolve();
  }

  return new Promise<void>((resolve, reject) => {
    const handleLoad = () => {
      cleanup();
      script.dataset.loaded = "true";
      resolve();
    };
    const handleError = () => {
      cleanup();
      reject(new Error(`Failed to load Visualize.js from ${script.src}`));
    };
    const cleanup = () => {
      script.removeEventListener("error", handleError);
      script.removeEventListener("load", handleLoad);
    };

    script.addEventListener("error", handleError);
    script.addEventListener("load", handleLoad);
  });
}
