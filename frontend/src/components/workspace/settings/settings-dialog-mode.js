export function shouldShowDesktopModelSettings({
  hasDesktopBridge,
  runtimeMode,
}) {
  return hasDesktopBridge && runtimeMode === "bundled";
}
