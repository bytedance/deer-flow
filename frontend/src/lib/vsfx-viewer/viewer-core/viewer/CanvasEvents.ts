export const CANVAS_EVENTS = {
  pointerDown: "pointerdown",
  pointerMove: "pointermove",
  pointerUp: "pointerup",
  wheel: "wheel",
} as const;

export type CanvasEventMap = typeof CANVAS_EVENTS;
