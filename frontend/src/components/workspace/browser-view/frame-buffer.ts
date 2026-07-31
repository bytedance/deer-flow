type CommitFrame = (url: string) => void;

/** Coalesces lossy browser frames to the display refresh rate. */
export class LatestBrowserFrameBuffer {
  private pendingFrame: Blob | null = null;
  private pendingFrameRequest: number | null = null;
  private objectUrl: string | null = null;

  constructor(private readonly commit: CommitFrame) {}

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
      this.objectUrl = nextUrl;
      this.commit(nextUrl);
    });
  }

  replaceWithUrl(url: string) {
    this.cancelPendingFrame();
    this.revokeCurrentObjectUrl();
    this.commit(url);
  }

  dispose() {
    this.cancelPendingFrame();
    this.revokeCurrentObjectUrl();
  }

  private cancelPendingFrame() {
    this.pendingFrame = null;
    if (this.pendingFrameRequest !== null) {
      cancelAnimationFrame(this.pendingFrameRequest);
      this.pendingFrameRequest = null;
    }
  }

  private revokeCurrentObjectUrl() {
    if (this.objectUrl !== null) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }
  }
}
