import { CANVAS_EVENTS, type IViewer, type ViewerInteractionEventMap } from "@/lib/vsfx-viewer/viewer-core";

export class GestureManager {
  private canvasEvents = [...CANVAS_EVENTS];
  private initialized = false;
  private readonly viewer: IViewer;

  constructor(viewer: IViewer) {
    this.viewer = viewer;
  }

  initialize() {
    if (this.initialized) {
      return;
    }

    this.canvasEvents = this.canvasEvents.filter(
      (eventName) => typeof (this as Record<string, unknown>)[eventName] === "function",
    );

    for (const eventName of this.canvasEvents) {
      const handler = (
        this as Record<string, (...args: Array<unknown>) => void>
      )[eventName].bind(this);

      (this as Record<string, unknown>)[eventName] = handler;
      this.viewer.on(
        eventName as keyof ViewerInteractionEventMap,
        handler as (payload: ViewerInteractionEventMap[keyof ViewerInteractionEventMap]) => void,
      );
    }

    this.initialized = true;
  }

  dispose() {
    if (!this.initialized) {
      return;
    }

    for (const eventName of this.canvasEvents) {
      this.viewer.off(
        eventName as keyof ViewerInteractionEventMap,
        (this as Record<string, (payload: unknown) => void>)[eventName],
      );
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
}
