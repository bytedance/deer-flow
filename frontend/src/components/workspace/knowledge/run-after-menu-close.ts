/**
 * Defer an action until the Radix menu (dropdown/context) has fully torn down
 * its dismissal layer — exit animation finished and the body pointer-events
 * restored. Opening a second modal layer (rename/delete dialog, chunk drawer)
 * synchronously from onSelect interleaves both layers' body pointer-events
 * bookkeeping in react-dismissable-layer, leaving `pointer-events: none`
 * stuck on <body> after the second layer closes: the page then looks frozen
 * and only a refresh recovers (right-click → 查看切片 → click outside
 * reproduces it). Poll instead of a fixed timeout so we don't guess the
 * animation length; the deadline keeps the action alive if the menu never
 * settles (e.g. happy-dom).
 */
export function runAfterMenuClose(action: () => void) {
  const deadline = Date.now() + 500;
  const tick = () => {
    if (document.body.style.pointerEvents !== "none" || Date.now() > deadline) {
      action();
      return;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
