import { uploadFiles, type UploadedFileInfo } from "./api";
import {
  promptInputFilePartToFile,
  type PromptInputFilePart,
} from "./prompt-input-files";

export type AttachmentUploadStatus =
  | "pending"
  | "uploading"
  | "uploaded"
  | "failed"
  | "cancelled";
type Entry = {
  status: AttachmentUploadStatus;
  result?: UploadedFileInfo;
  controller?: AbortController;
  promise?: Promise<void>;
};

/** One composer, one authenticated thread. Successful uploads survive a failed send. */
export class AttachmentUploadSession {
  private entries = new Map<File | string, Entry>();
  private listeners = new Set<() => void>();
  private version = 0;
  private active = true;
  private threadId?: string;
  private cancellations = 0;
  constructor(private upload = uploadFiles) {}
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  snapshot = () => this.version;
  private emit() {
    this.version++;
    this.listeners.forEach((listener) => listener());
  }
  private key(part: PromptInputFilePart) {
    return part.file ?? part.url;
  }
  status(part: PromptInputFilePart): AttachmentUploadStatus {
    return this.entries.get(this.key(part))?.status ?? "pending";
  }
  activate() {
    this.active = true;
  }
  deactivate() {
    this.cancellations++;
    this.active = false;
    for (const entry of this.entries.values()) {
      entry.controller?.abort();
      if (entry.status === "uploading") entry.status = "cancelled";
    }
    this.emit();
  }
  cancel(part: PromptInputFilePart) {
    this.cancellations++;
    const key = this.key(part);
    const entry = this.entries.get(key) ?? { status: "pending" };
    entry.controller?.abort();
    this.entries.set(key, { status: "cancelled" });
    this.emit();
  }
  async retry(part: PromptInputFilePart) {
    if (!this.threadId || !this.active) return;
    await this.start(part);
  }
  private start(part: PromptInputFilePart): Promise<void> {
    const key = this.key(part),
      current = this.entries.get(key);
    if (current?.status === "uploaded") return Promise.resolve();
    if (current?.status === "uploading") return current.promise!;
    const controller = new AbortController();
    const entry: Entry = { status: "uploading", controller };
    this.entries.set(key, entry);
    entry.promise = (async () => {
      try {
        if (!this.active || !this.threadId)
          throw new Error("Upload session is inactive");
        const file = await promptInputFilePartToFile(part, controller.signal);
        controller.signal.throwIfAborted();
        if (!file) throw new Error("Unable to prepare attachment");
        const response = await this.upload(
          this.threadId,
          [file],
          controller.signal,
        );
        controller.signal.throwIfAborted();
        if (!this.active || this.entries.get(key) !== entry) return;
        const result = response.files[0];
        if (
          !result ||
          response.files.length !== 1 ||
          response.skipped_files?.length
        )
          throw new Error("Attachment was not stored");
        entry.result = result;
        entry.status = "uploaded";
      } catch {
        if (this.entries.get(key) === entry)
          entry.status = controller.signal.aborted ? "cancelled" : "failed";
      } finally {
        entry.controller = undefined;
        this.emit();
      }
    })();
    this.emit();
    return entry.promise;
  }
  async uploadAll(
    threadId: string,
    parts: PromptInputFilePart[],
  ): Promise<UploadedFileInfo[]> {
    if (!this.active) throw new Error("Upload session is inactive");
    if (this.threadId && this.threadId !== threadId)
      throw new Error("Upload thread changed");
    this.threadId = threadId;
    const cancellations = this.cancellations;
    // Three workers bound memory and requests. A cancelled queued item stays cancelled this attempt.
    const queue = parts.map((part) => {
      const key = this.key(part);
      if (["failed", "cancelled"].includes(this.status(part)))
        this.entries.set(key, { status: "pending" });
      return part;
    });
    this.emit();
    await Promise.all(
      Array.from({ length: Math.min(3, queue.length) }, async () => {
        while (queue.length && this.active) {
          const part = queue.shift()!;
          if (this.status(part) !== "cancelled") await this.start(part);
        }
      }),
    );
    if (
      !this.active ||
      cancellations !== this.cancellations ||
      parts.some((part) => this.status(part) !== "uploaded")
    )
      throw new Error("Attachments are not ready");
    return parts.map((part) => this.entries.get(this.key(part))!.result!);
  }
}
