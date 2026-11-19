// In-memory ring buffer of tool calls plus summary stats for the monitor UI.
// Entries can be updated in place (a job goes running -> done); every change bumps a
// revision so the UI can poll sinceRev and redraw only what changed.

export class CallLog {
  #entries = [];
  #nextId = 1;
  #rev = 0;
  #total = 0;
  #errors = 0;

  constructor({ capacity = 500, onAppend, onUpdate } = {}) {
    this.capacity = capacity;
    this.onAppend = onAppend;
    this.onUpdate = onUpdate;
  }

  append(fields) {
    const entry = { id: this.#nextId++, rev: ++this.#rev, ts: new Date().toISOString(), status: 'done', ...fields };
    this.#entries.push(entry);
    if (this.#entries.length > this.capacity) this.#entries.shift();
    if (entry.status === 'done') this.#count(entry);
    this.onAppend?.(entry);
    return entry;
  }

  update(id, fields) {
    const entry = this.#entries.find((e) => e.id === id);
    if (!entry) return null;
    const wasDone = entry.status === 'done';
    Object.assign(entry, fields, { rev: ++this.#rev });
    if (!wasDone && entry.status === 'done') this.#count(entry);
    this.onUpdate?.(entry);
    return entry;
  }

  since(id = 0) {
    return this.#entries.filter((e) => e.id > id);
  }

  sinceRev(rev = 0) {
    return this.#entries.filter((e) => e.rev > rev);
  }

  stats() {
    const done = this.#entries.filter((e) => e.status === 'done');
    const latencies = done.map((e) => e.latencyMs).filter((ms) => typeof ms === 'number');
    let avgMs = null;
    let p95Ms = null;
    if (latencies.length) {
      avgMs = round(latencies.reduce((sum, ms) => sum + ms, 0) / latencies.length);
      const sorted = [...latencies].sort((x, y) => x - y);
      p95Ms = sorted[Math.ceil(0.95 * sorted.length) - 1];
    }
    return {
      total: this.#total,
      errors: this.#errors,
      running: this.#entries.length - done.length,
      avgMs,
      p95Ms,
      lastId: this.#nextId - 1,
      lastRev: this.#rev,
    };
  }

  #count(entry) {
    this.#total++;
    if (!entry.ok) this.#errors++;
  }
}

const round = (n) => Math.round(n * 100) / 100;
