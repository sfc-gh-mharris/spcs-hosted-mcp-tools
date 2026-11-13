// Sends add() calls on a fixed interval so the monitor shows steady traffic.

export const MIN_INTERVAL_MS = 500;
export const MAX_INTERVAL_MS = 60000;

export class TrafficGenerator {
  #timer = null;
  #inFlight = false;
  #intervalMs = 2000;
  #sent = 0;
  #skipped = 0;

  constructor({ call, random = Math.random }) {
    this.call = call;
    this.random = random;
  }

  start(intervalMs = this.#intervalMs) {
    this.stop();
    this.#intervalMs = Math.min(MAX_INTERVAL_MS, Math.max(MIN_INTERVAL_MS, Math.round(intervalMs)));
    this.#timer = setInterval(() => this.#tick(), this.#intervalMs);
  }

  stop() {
    if (this.#timer) clearInterval(this.#timer);
    this.#timer = null;
  }

  status() {
    return { enabled: this.#timer !== null, intervalMs: this.#intervalMs, sent: this.#sent, skipped: this.#skipped };
  }

  #tick() {
    // A slow server should not pile up overlapping calls.
    if (this.#inFlight) {
      this.#skipped++;
      return;
    }
    this.#inFlight = true;
    this.#sent++;
    const a = Math.floor(this.random() * 100);
    const b = Math.floor(this.random() * 100);
    Promise.resolve()
      .then(() => this.call(a, b, 'traffic'))
      .catch(() => {})
      .finally(() => {
        this.#inFlight = false;
      });
  }
}
