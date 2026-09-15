import { z } from "zod";

const fields = {
  notification_enabled: z.boolean().nullable(),
  model_name: z.string().max(200).nullable(),
  mode: z.enum(["flash", "thinking", "pro", "ultra"]).nullable(),
  reasoning_effort: z.enum(["minimal", "low", "medium", "high"]).nullable(),
};
const schema = z.object(fields).partial();
export type Preferences = z.infer<typeof schema>;

/** Keep valid individual preferences; never copy arbitrary runtime context. */
export function parsePreferences(value: unknown): Preferences {
  if (!value || typeof value !== "object") return {};
  const valid: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(fields)) {
    const parsed = field.safeParse((value as Record<string, unknown>)[key]);
    if (parsed.success) valid[key] = parsed.data;
  }
  return schema.parse(valid);
}

interface SyncIO {
  read: () => Promise<Preferences>;
  patch: (value: Preferences) => Promise<void>;
  apply: (value: Preferences) => void;
  savePending: (value: Preferences) => void;
  saveConfirmed?: (value: Preferences) => void;
}

/** One instance belongs to one account and one tab, including its outbox. */
export class PreferencesSync {
  private stopped = false;
  private running?: Promise<void>;

  constructor(
    private readonly io: SyncIO,
    private confirmed: Preferences,
    private pending: Preferences,
  ) {
    this.publish();
  }

  private publish() {
    this.io.apply({ ...this.confirmed, ...this.pending });
  }

  edit(value: Preferences) {
    if (this.stopped) return;
    this.pending = { ...this.pending, ...value };
    this.io.savePending(this.pending);
    this.publish();
  }

  stop() {
    this.stopped = true;
  }

  flush(): Promise<void> {
    if (this.stopped) return Promise.resolve();
    this.running ??= this.run().finally(() => {
      this.running = undefined;
    });
    return this.running;
  }

  private async run() {
    const remote = await this.io.read();
    if (this.stopped) return;
    this.confirmed = remote;
    this.io.saveConfirmed?.(this.confirmed);
    this.publish();
    while (!this.stopped && Object.keys(this.pending).length) {
      const sent = { ...this.pending };
      await this.io.patch(sent);
      if (this.stopped) return;
      this.confirmed = { ...this.confirmed, ...sent };
      this.io.saveConfirmed?.(this.confirmed);
      for (const key of Object.keys(sent) as (keyof Preferences)[]) {
        if (this.pending[key] === sent[key]) delete this.pending[key];
      }
      this.io.savePending(this.pending);
      this.publish();
    }
  }
}
