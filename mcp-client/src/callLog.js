// In-memory ring buffer of tool calls plus summary stats for the monitor UI.

export class CallLog {
  #entries = [];
  #nextId = 1;
  #total = 0;
  #errors = 0;

  constructor({ capacity = 500, onAppend } = {}) {
    this.capacity = capacity;
    this.onAppend = onAppend;
  }

  append(fields) {
    const entry = { id: this.#nextId++, ts: new Date().toISOString(), ...fields };
    this.#entries.push(entry);
    if (this.#entries.length > this.capacity) this.#entries.shift();
    this.#total++;
    if (!entry.ok) this.#errors++;
    this.onAppend?.(entry);
    return entry;
  }

  since(id = 0) {
    return this.#entries.filter((e) => e.id > id);
  }

  stats() {
    const latencies = this.#entries.map((e) => e.latencyMs).filter((ms) => typeof ms === 'number');
    let avgMs = null;
    let p95Ms = null;
    if (latencies.length) {
      avgMs = round(latencies.reduce((sum, ms) => sum + ms, 0) / latencies.length);
      const sorted = [...latencies].sort((x, y) => x - y);
      p95Ms = sorted[Math.ceil(0.95 * sorted.length) - 1];
    }
    return { total: this.#total, errors: this.#errors, avgMs, p95Ms, lastId: this.#nextId - 1 };
  }
}

const round = (n) => Math.round(n * 100) / 100;
