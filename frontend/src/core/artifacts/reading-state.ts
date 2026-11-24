/** Small, in-memory reading preferences; cleared when the authenticated viewer changes. */
const states = new Map<string, string>();
let owner: string | undefined;
export function readingStateAccess(viewer: string, key: string) {
  if (owner !== viewer) {
    states.clear();
    owner = viewer;
  }
  return {
    get: (): unknown =>
      owner === viewer && states.has(key)
        ? JSON.parse(states.get(key)!)
        : undefined,
    set: (state: unknown) => {
      if (owner !== viewer) return;
      try {
        const json = JSON.stringify(state);
        if (!json || json.length > 16_384) return;
        states.delete(key);
        states.set(key, json);
        while (states.size > 50) states.delete(states.keys().next().value!);
      } catch {
        /* Extension state must be serializable and bounded. */
      }
    },
  };
}
