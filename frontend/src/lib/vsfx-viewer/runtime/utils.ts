import { getVisualizeAssetPaths } from "./asset-paths";

type LoadParams = {
  crossOrigin?: string;
};

type ProgressHandler = ((event: ProgressEvent<EventTarget>) => void) | undefined;

export type VisualizeProgressState = {
  loaded: number;
  percent: number;
  total: number;
};

export type LoadVisualizeLibraryOptions = {
  crossOrigin?: string;
  onProgress?: (state: VisualizeProgressState) => void;
  scriptUrl?: string;
  wasmUrl?: string;
};

export async function ensureVisualizeScript(
  scriptUrl = getVisualizeAssetPaths().scriptUrl,
  params: LoadParams = {},
) {
  if (typeof window === "undefined" || typeof document === "undefined") {
    throw new Error("Visualize.js can only be loaded in a browser environment");
  }

  await loadVisualizeScript(scriptUrl, params);
}

export async function loadVisualizeLibrary({
  crossOrigin,
  onProgress,
  scriptUrl = getVisualizeAssetPaths().scriptUrl,
  wasmUrl = getVisualizeAssetPaths().wasmUrl,
}: LoadVisualizeLibraryOptions = {}) {
  await ensureVisualizeScript(scriptUrl, { crossOrigin });

  const factory = window.getVisualizeLibInst;

  if (!factory) {
    throw new Error("Visualize.js factory was not found on window.getVisualizeLibInst");
  }

  const script = getFactoryScript(factory) ?? findExistingVisualizeScript(scriptUrl);
  const restoreInstantiate = wrapStreamingWithProgress(
    "instantiateStreaming",
    onProgress && ((event) => onProgress(toVisualizeProgressState(event))),
  );
  const restoreCompile = wrapStreamingWithProgress(
    "compileStreaming",
    onProgress && ((event) => onProgress(toVisualizeProgressState(event))),
  );

  try {
    return await new Promise<unknown>((resolve, reject) => {
      const library = factory({
        TOTAL_MEMORY: 134217728,
        onprogress: (event) => {
          onProgress?.(toVisualizeProgressState(event));
        },
        urlMemFile: wasmUrl,
      });

      library.loadWasmError = reject;

      if (Array.isArray(library.postRun)) {
        library.postRun.push(() => {
          if (script) {
            setFactoryScript(factory, script);
          }
          resolve(library);
        });
        return;
      }

      if (script) {
        setFactoryScript(factory, script);
      }
      resolve(library);
    });
  } finally {
    restoreInstantiate();
    restoreCompile();
  }
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

async function resolveResponse(source: unknown): Promise<Response | null> {
  try {
    if (source instanceof Response) {
      return source;
    }

    if (source && typeof source === "object" && "then" in source) {
      const awaited = await (source as Promise<unknown>);
      return awaited instanceof Response ? awaited : null;
    }
  } catch {
    return null;
  }

  return null;
}

function createProgressEvent(loaded: number, total: number, lengthComputable: boolean) {
  return new ProgressEvent("progress", {
    lengthComputable,
    loaded,
    total,
  });
}

function wrapStreamingWithProgress(
  method: "instantiateStreaming" | "compileStreaming",
  onProgress: ProgressHandler,
) {
  const original = (WebAssembly as Record<string, unknown>)[method];

  if (typeof original !== "function" || typeof ReadableStream === "undefined") {
    return () => undefined;
  }

  const wrapped = async (source: unknown, ...rest: unknown[]) => {
    const response = await resolveResponse(source);

    if (!response?.body || typeof response.body.getReader !== "function") {
      return (original as (...args: unknown[]) => unknown).call(WebAssembly, source, ...rest);
    }

    const reader = response.body.getReader();
    const totalFromHeader = Number(response.headers.get("Content-Length"));
    const hasTotal = Number.isFinite(totalFromHeader) && totalFromHeader > 0;
    let loaded = 0;

    const stream = new ReadableStream<Uint8Array>({
      async pull(controller) {
        const { done, value } = await reader.read();

        if (done) {
          if (onProgress) {
            const total = hasTotal ? totalFromHeader : loaded;
            onProgress(createProgressEvent(total, total, true));
          }
          controller.close();
          return;
        }

        loaded += value.byteLength;

        if (onProgress) {
          onProgress(createProgressEvent(loaded, hasTotal ? totalFromHeader : loaded, hasTotal));
        }

        controller.enqueue(value);
      },
      cancel(reason) {
        void reader.cancel(reason);
      },
    });

    const headers = new Headers();
    response.headers.forEach((value, key) => headers.append(key, value));

    const monitoredResponse = new Response(stream, {
      headers,
      status: response.status,
      statusText: response.statusText,
    });

    return (original as (...args: unknown[]) => unknown).call(
      WebAssembly,
      Promise.resolve(monitoredResponse),
      ...rest,
    );
  };

  (WebAssembly as Record<string, unknown>)[method] = wrapped;

  return () => {
    (WebAssembly as Record<string, unknown>)[method] = original;
  };
}

function loadScript(url: string, params: LoadParams = {}): Promise<HTMLScriptElement> {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = url;
    script.async = true;
    script.crossOrigin = params.crossOrigin ?? null;
    script.dataset.visualizeScript = "true";
    script.onload = () => resolve(script);
    script.onerror = () => {
      script.remove();
      reject(new Error(`GET ${url} failed to load script`));
    };
    document.body.append(script);
  });
}

async function loadVisualizeScript(url: string, params: LoadParams = {}) {
  if (window.getVisualizeLibInst) {
    const script =
      getFactoryScript(window.getVisualizeLibInst) ?? findExistingVisualizeScript(url);

    if (script) {
      if (script.src === toAbsoluteUrl(url)) {
        await waitForScript(script);
        return script;
      }

      script.remove();
    }

    delete window.getVisualizeLibInst;
  }

  const existing = findExistingVisualizeScript(url);

  if (existing) {
    await waitForScript(existing);
    return existing;
  }

  return loadScript(url, params);
}

function clampPercent(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.min(100, Math.max(0, value));
}

function findExistingVisualizeScript(scriptUrl: string) {
  return document.querySelector<HTMLScriptElement>(
    `script[data-visualize-script="true"][src="${toAbsoluteUrl(scriptUrl)}"]`,
  );
}

function toAbsoluteUrl(url: string) {
  return new URL(url, window.location.href).href;
}

function getFactoryScript(factory: typeof window.getVisualizeLibInst) {
  return factory?.script;
}

function setFactoryScript(factory: typeof window.getVisualizeLibInst, script: HTMLScriptElement) {
  if (factory) {
    factory.script = script;
  }
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
