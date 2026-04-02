import type { ResolvedOptions } from "../options/IOptions";

import type { ViewerBinarySource, ViewerEventMap } from "./ViewerEvents";

export interface IViewer {
  clearSlices(): void;
  dispose(): void;
  executeCommand(name: string, ...args: unknown[]): unknown;
  getContainer(): HTMLElement;
  getOptions(): ResolvedOptions;
  getSelected(): Array<string | number>;
  on<TName extends keyof ViewerEventMap>(
    eventName: TName,
    listener: (payload: ViewerEventMap[TName]) => void,
  ): () => void;
  open(input: ViewerBinarySource): Promise<void>;
  render(): void;
  resize(): void;
  update(): void;
}
