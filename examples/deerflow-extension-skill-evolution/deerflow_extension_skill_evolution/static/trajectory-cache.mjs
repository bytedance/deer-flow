// A mounted page owns this cache: never persist caller-owned trajectories in
// localStorage or share them globally across authenticated page contexts.
export class TrajectoryCache {
  constructor({ load, signal, onChange = () => {}, concurrency = 2, ttlMs = 60_000, errorTtlMs = 5_000, maxEntries = 32, now = Date.now }) {
    this.fetch = load;
    this.signal = signal;
    this.onChange = onChange;
    this.concurrency = concurrency;
    this.ttlMs = ttlMs;
    this.errorTtlMs = errorTtlMs;
    this.maxEntries = maxEntries;
    this.now = now;
    this.entries = new Map();
    this.queue = [];
    this.active = 0;
    this.disposed = !!signal?.aborted;
    signal?.addEventListener("abort", () => { this.disposed = true; this.clear(); }, { once: true });
  }

  get(name) {
    const entry = this.entries.get(name);
    if (entry) {
      this.entries.delete(name);
      this.entries.set(name, entry);
    }
    return entry;
  }

  load(name, { force = false, priority = false } = {}) {
    if (this.disposed) return Promise.resolve(null);
    const previous = this.get(name);
    if (!force && previous) {
      if (previous.loading) {
        const queued = this.queue.find((job) => job.entry === previous);
        if (priority && queued) {
          queued.priority = true;
          this.queue = [queued, ...this.queue.filter((job) => job !== queued)];
        }
        return previous.promise;
      }
      const ttl = previous.error ? this.errorTtlMs : this.ttlMs;
      if (this.now() - previous.completedAt < ttl) return Promise.resolve(previous.data);
    }
    // Each replacement has its own identity: late replies can never overwrite
    // a refresh or an annotation write's newer request.
    const entry = { data: previous?.data || null, loading: true, error: null, completedAt: null };
    entry.promise = new Promise((resolve) => { entry.resolve = resolve; });
    this.entries.set(name, entry);
    this.queue = this.queue.filter((job) => {
      if (job.name !== name) return true;
      job.entry.resolve(null);
      return false;
    });
    const job = { name, entry, priority };
    if (priority) this.queue.unshift(job);
    else this.queue.push(job);
    this.trim();
    this.notify(name);
    this.pump();
    return entry.promise;
  }

  warm(names) {
    if (this.disposed) return;
    const wanted = new Set(names);
    // A page change drops obsolete speculative work, retaining explicit clicks.
    this.queue = this.queue.filter((job) => {
      if (job.priority || wanted.has(job.name)) return true;
      if (this.entries.get(job.name) === job.entry) this.entries.delete(job.name);
      job.entry.resolve(null);
      return false;
    });
    for (const name of wanted) this.load(name);
  }

  clear() {
    for (const job of this.queue) job.entry.resolve(null);
    this.queue = [];
    this.entries.clear();
  }

  notify(name) {
    if (!this.disposed) this.onChange(name);
  }

  trim() {
    for (const [name, entry] of this.entries) {
      if (this.entries.size <= this.maxEntries) break;
      if (!entry.loading) this.entries.delete(name);
    }
  }

  pump() {
    while (!this.disposed && this.active < this.concurrency && this.queue.length) {
      const { name, entry } = this.queue.shift();
      this.active += 1;
      Promise.resolve().then(() => this.disposed ? null : this.fetch(name)).then(
        (data) => { entry.data = data; entry.error = null; },
        (error) => {
          entry.error = error?.message || "INTERNAL";
          if (["UNAUTHENTICATED", "FORBIDDEN", "UNAVAILABLE"].includes(entry.error)) entry.data = null;
        },
      ).finally(() => {
        this.active -= 1;
        entry.loading = false;
        entry.completedAt = this.now();
        if (!this.disposed && this.entries.get(name) === entry) {
          this.trim();
          this.notify(name);
        }
        entry.resolve(this.disposed ? null : entry.data);
        this.pump();
      });
    }
  }
}
