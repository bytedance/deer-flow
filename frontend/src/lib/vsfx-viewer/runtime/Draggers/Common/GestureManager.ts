import { CANVAS_EVENTS, type IViewer, type ViewerInteractionEventMap } from "@/lib/vsfx-viewer/viewer-core";

export class GestureManager {
  private canvasEvents = [...CANVAS_EVENTS];
  private initialized = false;
  private readonly viewer: IViewer;
  private readonly boundHandlers: Partial<{
    [TName in keyof ViewerInteractionEventMap]: (
      payload: ViewerInteractionEventMap[TName],
    ) => void;
  }> = {};

  constructor(viewer: IViewer) {
    this.viewer = viewer;
  }

  initialize() {
    if (this.initialized) {
      return;
    }

    this.canvasEvents = this.canvasEvents.filter(
      (eventName) => typeof this.getHandler(eventName) === "function",
    );

    for (const eventName of this.canvasEvents) {
      const handler = this.getHandler(eventName);

      if (!handler) {
        continue;
      }

      const boundHandler = handler.bind(this) as (payload: typeof eventName extends never
        ? never
        : ViewerInteractionEventMap[typeof eventName]) => void;

      this.boundHandlers[eventName] = boundHandler;
      this.viewer.on(
        eventName,
        boundHandler as (payload: ViewerInteractionEventMap[typeof eventName]) => void,
      );
    }

    this.initialized = true;
  }

  dispose() {
    if (!this.initialized) {
      return;
    }

    for (const eventName of this.canvasEvents) {
      const handler = this.boundHandlers[eventName];

      if (!handler) {
        continue;
      }

      this.viewer.off(
        eventName,
        handler as (payload: ViewerInteractionEventMap[typeof eventName]) => void,
      );
      delete this.boundHandlers[eventName];
    }

    this.initialized = false;
  }

  protected pointercancel(event: PointerEvent) {
    void event;
  }

  protected pointerdown(event: PointerEvent) {
    void event;
  }

  protected pointerleave(event: PointerEvent) {
    void event;
  }

  protected pointermove(event: PointerEvent) {
    void event;
  }

  protected pointerup(event: PointerEvent) {
    void event;
  }

  private getHandler<TName extends keyof ViewerInteractionEventMap>(eventName: TName) {
    const candidate = this[eventName as keyof this];

    return typeof candidate === "function"
      ? (candidate as (payload: ViewerInteractionEventMap[TName]) => void)
      : undefined;
  }
}
