import type { ResolvedOptions } from "../options/IOptions";

import type { CanvasEventMap } from "./CanvasEvents";
import type { ViewerBinarySource, ViewerEventMap } from "./ViewerEvents";

export type ViewerInteractionEventMap = ViewerEventMap & CanvasEventMap;

export interface IViewer {
  clearSlices(): void;
  dispose(): void;
  executeCommand(name: string, ...args: unknown[]): unknown;
  getContainer(): HTMLElement;
  getOptions(): ResolvedOptions;
  getSelected(): Array<string | number>;
  on<TName extends keyof ViewerInteractionEventMap>(
    eventName: TName,
    listener: (payload: ViewerInteractionEventMap[TName]) => void,
  ): () => void;
  off<TName extends keyof ViewerInteractionEventMap>(
    eventName: TName,
    listener: (payload: ViewerInteractionEventMap[TName]) => void,
  ): void;
  open(input: ViewerBinarySource): Promise<void>;
  render(): void;
  resize(): void;
  update(): void;
}
