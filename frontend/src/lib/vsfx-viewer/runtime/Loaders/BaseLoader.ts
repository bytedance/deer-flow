import type { ViewerBinarySource, ViewerEventMap } from "@/lib/vsfx-viewer/viewer-core";

export type LoaderContext = {
  emit: <TName extends keyof ViewerEventMap>(
    eventName: TName,
    payload: ViewerEventMap[TName],
  ) => void;
  getVisualizeViewer: () => Record<string, unknown> | null;
};

export abstract class BaseLoader {
  protected readonly context: LoaderContext;

  constructor(context: LoaderContext) {
    this.context = context;
  }

  abstract load(source: ViewerBinarySource): Promise<void>;
}
