/** Each request owns one disposable worker; no stale result or parser survives it. */
export async function prepareOffice(
  bytes,
  kind,
  signal,
  {
    timeoutMs = 15000,
    workerFactory = () =>
      new Worker(new URL("./office-worker.mjs", import.meta.url), {
        type: "module",
      }),
  } = {},
) {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    let worker,
      timer,
      settled = false;
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      if (worker) {
        worker.onmessage = worker.onerror = worker.onmessageerror = null;
        worker.terminate();
      }
      if (error) reject(error);
      else resolve(result);
    };
    const abort = () =>
      finish(
        signal.reason ?? new DOMException("Preview cancelled", "AbortError"),
      );
    try {
      worker = workerFactory();
      signal.addEventListener("abort", abort, { once: true });
      if (signal.aborted) {
        abort();
        return;
      }
      timer = setTimeout(
        () => finish(new Error("Office preview parsing timed out")),
        timeoutMs,
      );
      worker.onmessage = ({ data }) => {
        if (data.error) finish(new Error(data.error));
        else if (Object.hasOwn(data, "result")) finish(null, data.result);
      };
      worker.onerror = (event) => {
        event.preventDefault();
        finish(new Error("Office preview worker failed"));
      };
      worker.onmessageerror = () =>
        finish(new Error("Office preview worker response failed"));
      // Keep the host's original read buffer intact; transfer only our private copy.
      const input = bytes.slice(0);
      worker.postMessage({ bytes: input, kind }, [input]);
    } catch (error) {
      finish(error);
    }
  });
}
