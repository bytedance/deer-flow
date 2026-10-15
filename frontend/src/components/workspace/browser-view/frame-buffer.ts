/** Coalesces lossy browser frames to the display refresh rate. */
export class LatestBrowserFrameBuffer {
  private pendingFrame: Blob | null = null;
  private pendingFrameRequest: number | null = null;
  private currentUrl: string | null = null;
  private readonly listeners = new Set<() => void>();

  getSnapshot = () => this.currentUrl;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  push(frame: Blob) {
    this.pendingFrame = frame;
    if (this.pendingFrameRequest !== null) return;

    this.pendingFrameRequest = requestAnimationFrame(() => {
      this.pendingFrameRequest = null;
      const latestFrame = this.pendingFrame;
      this.pendingFrame = null;
      if (!latestFrame) return;

      const nextUrl = URL.createObjectURL(latestFrame);
      this.revokeCurrentObjectUrl();
      this.currentUrl = nextUrl;
      this.notify();
    });
  }

  replaceWithUrl(url: string) {
    this.cancelPendingFrame();
    this.revokeCurrentObjectUrl();
    this.currentUrl = url;
    this.notify();
  }

  dispose() {
    this.cancelPendingFrame();
    this.revokeCurrentObjectUrl();
    this.notify();
  }

  private cancelPendingFrame() {
    this.pendingFrame = null;
    if (this.pendingFrameRequest !== null) {
      cancelAnimationFrame(this.pendingFrameRequest);
      this.pendingFrameRequest = null;
    }
  }

  private revokeCurrentObjectUrl() {
    if (this.currentUrl?.startsWith("blob:")) {
      URL.revokeObjectURL(this.currentUrl);
    }
    this.currentUrl = null;
  }

  private notify() {
    this.listeners.forEach((listener) => listener());
  }
}
