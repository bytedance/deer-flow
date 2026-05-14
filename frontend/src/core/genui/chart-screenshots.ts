import { create } from "zustand";

import { uploadFiles } from "@/core/uploads/api";

interface PendingScreenshot {
  dataUrl: string;
  filename: string;
}

interface ChartScreenshotState {
  pending: Map<string, PendingScreenshot[]>;
  uploaded: Map<string, string[]>;
  addCapture: (threadId: string, dataUrl: string, filename: string) => void;
  getUploadedPaths: (threadId: string) => string[];
  clear: (threadId: string) => void;
  _setUploaded: (threadId: string, paths: string[]) => void;
}

export const useChartScreenshotStore = create<ChartScreenshotState>(
  (set, get) => ({
    pending: new Map(),
    uploaded: new Map(),
    addCapture: (threadId, dataUrl, filename) =>
      set((state) => {
        const next = new Map(state.pending);
        const items = next.get(threadId) ?? [];
        next.set(threadId, [...items, { dataUrl, filename }]);
        return { pending: next };
      }),
    getUploadedPaths: (threadId) => get().uploaded.get(threadId) ?? [],
    clear: (threadId) =>
      set((state) => {
        const nextPending = new Map(state.pending);
        const nextUploaded = new Map(state.uploaded);
        nextPending.delete(threadId);
        nextUploaded.delete(threadId);
        return { pending: nextPending, uploaded: nextUploaded };
      }),
    _setUploaded: (threadId, paths) =>
      set((state) => {
        const nextUploaded = new Map(state.uploaded);
        nextUploaded.set(threadId, paths);
        const nextPending = new Map(state.pending);
        nextPending.delete(threadId);
        return { pending: nextPending, uploaded: nextUploaded };
      }),
  }),
);

export function addChartCapture(threadId: string, dataUrl: string, filename: string) {
  useChartScreenshotStore.getState().addCapture(threadId, dataUrl, filename);
}

function dataUrlToFile(dataUrl: string, filename: string): File {
  const [header, base64Data] = dataUrl.split(",");
  const mime = header?.match(/:(.*?);/)?.[1] ?? "image/png";
  const binary = atob(base64Data ?? "");
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new File([bytes], filename, { type: mime });
}

export async function uploadPendingScreenshots(threadId: string): Promise<string[]> {
  const state = useChartScreenshotStore.getState();
  const alreadyUploaded = state.uploaded.get(threadId);
  if (alreadyUploaded && alreadyUploaded.length > 0) {
    return alreadyUploaded;
  }

  const pending = state.pending.get(threadId);
  if (!pending || pending.length === 0) {
    return [];
  }

  const valid = pending.filter((p) => p.dataUrl?.startsWith("data:"));
  if (valid.length === 0) {
    state._setUploaded(threadId, []);
    return [];
  }

  const files = valid.map((p) => dataUrlToFile(p.dataUrl, p.filename));
  try {
    const result = await uploadFiles(threadId, files);
    const paths = result.files
      .map((f) => f.virtual_path)
      .filter((p): p is string => typeof p === "string" && p !== "");
    state._setUploaded(threadId, paths);
    return paths;
  } catch {
    return [];
  }
}
