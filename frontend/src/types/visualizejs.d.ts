export {};

declare global {
  type VisualizeProgressHandler = (event: ProgressEvent<EventTarget>) => void;

  interface VisualizeLibraryInitOptions {
    TOTAL_MEMORY?: number;
    onprogress?: VisualizeProgressHandler;
    urlMemFile?: string;
  }

  interface VisualizeLibraryInstance {
    loadWasmError?: (error: unknown) => void;
    postRun: Array<() => void>;
  }

  interface VisualizeLibraryFactory {
    (params?: VisualizeLibraryInitOptions): VisualizeLibraryInstance;
    script?: HTMLScriptElement;
  }

  interface Window {
    getVisualizeLibInst?: VisualizeLibraryFactory;
  }
}
