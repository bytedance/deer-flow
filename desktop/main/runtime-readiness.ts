type MinimalResponse = {
  ok: boolean;
  json: () => Promise<unknown>;
};

type WaitForModelsApiReadyOptions = {
  timeoutMs?: number;
  retryDelayMs?: number;
  fetchFn?: (input: string) => Promise<MinimalResponse>;
  sleepFn?: (ms: number) => Promise<void>;
};

function sleep(ms: number) {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });
}

export async function waitForModelsApiReady(
  modelsApiUrl: string,
  options: WaitForModelsApiReadyOptions = {},
) {
  const timeoutMs = options.timeoutMs ?? 120_000;
  const retryDelayMs = options.retryDelayMs ?? 500;
  const fetchFn = options.fetchFn ?? ((input: string) => fetch(input) as Promise<MinimalResponse>);
  const sleepFn = options.sleepFn ?? sleep;
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetchFn(modelsApiUrl);
      if (response.ok) {
        const payload = await response.json();
        if (
          typeof payload === "object" &&
          payload !== null &&
          Array.isArray(Reflect.get(payload, "models"))
        ) {
          return;
        }
      }
    } catch {
      // retry until timeout
    }

    await sleepFn(retryDelayMs);
  }

  throw new Error(`Timed out waiting for models API readiness: ${modelsApiUrl}`);
}
