/** Native module graphs preserve relative URLs and credentialed chunk imports. */
export function importAssetModule(url: string): Promise<{ default: unknown }> {
  const absoluteURL = new URL(url, document.baseURI).href;
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.type = "module";
    script.crossOrigin = "use-credentials";
    script.src = absoluteURL;
    const cleanup = () => {
      clearTimeout(timer);
      script.onload = script.onerror = null;
      script.remove();
    };
    const fail = (error: unknown) => {
      cleanup();
      reject(
        error instanceof Error
          ? error
          : new Error("Plugin module failed", { cause: error }),
      );
    };
    // Bound evaluation as well as network loading (including top-level await).
    const timer = setTimeout(
      () => fail(new Error("Plugin module timed out")),
      30_000,
    );
    script.onload = () => {
      // The credentialed script populated the document's module map. Reuse that
      // module instance to obtain its exports; do not fetch it as a Blob.
      void import(/* webpackIgnore: true */ absoluteURL).then(
        (module: { default: unknown }) => {
          cleanup();
          resolve(module);
        },
        fail,
      );
    };
    script.onerror = () => fail(new Error("Plugin module unavailable"));
    document.head.append(script);
  });
}
