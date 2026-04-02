export const CANVAS_EVENTS = [
  "click",
  "contextmenu",
  "dblclick",
  "mousedown",
  "mouseleave",
  "mousemove",
  "mouseup",
  "pointercancel",
  "pointerdown",
  "pointerleave",
  "pointermove",
  "pointerup",
  "touchcancel",
  "touchend",
  "touchmove",
  "touchstart",
  "wheel",
] as const;

export type CanvasEventMap = {
  click: MouseEvent;
  contextmenu: MouseEvent;
  dblclick: MouseEvent;
  mousedown: MouseEvent;
  mouseleave: MouseEvent;
  mousemove: MouseEvent;
  mouseup: MouseEvent;
  pointercancel: PointerEvent;
  pointerdown: PointerEvent;
  pointerleave: PointerEvent;
  pointermove: PointerEvent;
  pointerup: PointerEvent;
  touchcancel: TouchEvent;
  touchend: TouchEvent;
  touchmove: TouchEvent;
  touchstart: TouchEvent;
  wheel: WheelEvent;
};
