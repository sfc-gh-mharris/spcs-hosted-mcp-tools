// Monitor UI. Polls the backend every 2s; all values are rendered with textContent.
const POLL_MS = 2000;
const MAX_ROWS = 200;
let lastId = 0;
let trafficOn = false;

const $ = (id) => document.getElementById(id);

async function api(path, init) {
  const res = await fetch(path, init);
  const body = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, body };
}

const postJson = (path, body) =>
  api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function renderStatus(s) {
  const status = $('status');
  status.className = `status ${s.connected ? 'ok' : s.lastError ? 'down' : 'unknown'}`;
  $('status-text').textContent = s.connected ? 'Connected to MCP server' : s.lastError ? 'MCP server unreachable' : 'Not connected yet';
  $('server-url').textContent = s.url ?? '-';
  $('server-name').textContent = s.serverInfo ? `${s.serverInfo.name} ${s.serverInfo.version ?? ''}`.trim() : '-';
  $('server-protocol').textContent = s.protocolVersion ?? '-';
  $('server-error').textContent = s.lastError ?? '-';
  renderTraffic(s.traffic);
}

function renderTraffic(t) {
  if (!t) return;
  trafficOn = t.enabled;
  const button = $('traffic-toggle');
  button.textContent = t.enabled ? 'Stop' : 'Start';
  button.classList.toggle('stop', t.enabled);
  $('traffic-status').textContent = t.enabled
    ? `Running every ${t.intervalMs} ms. Sent ${t.sent}, skipped ${t.skipped}.`
    : `Stopped. Sent ${t.sent} so far.`;
}

function renderStats(stats) {
  $('stat-total').textContent = stats.total;
  $('stat-errors').textContent = stats.errors;
  $('stat-avg').textContent = stats.avgMs ?? '-';
  $('stat-p95').textContent = stats.p95Ms ?? '-';
}

function addRows(entries) {
  const tbody = $('log');
  for (const e of entries) {
    const row = el('tr', undefined, e.ok ? '' : 'err');
    row.append(
      el('td', String(e.id), 'num'),
      el('td', new Date(e.ts).toLocaleTimeString()),
    );
    const sourceCell = el('td');
    sourceCell.append(el('span', e.source, `badge ${e.source}`));
    row.append(
      sourceCell,
      el('td', `${e.args.a} + ${e.args.b}`),
      el('td', e.ok ? String(e.result) : '-', 'num'),
      el('td', String(e.latencyMs), 'num'),
      el('td', e.ok ? 'ok' : `${e.errorKind}: ${e.error}`),
    );
    tbody.prepend(row);
  }
  while (tbody.rows.length > MAX_ROWS) tbody.deleteRow(-1);
}

async function loadTools() {
  const list = $('tools');
  list.replaceChildren(el('li', 'Loading...', 'muted'));
  const { ok, body } = await api('api/tools');
  if (!ok) {
    list.replaceChildren(el('li', `Could not list tools: ${body.error ?? 'unknown error'}`, 'muted'));
    return;
  }
  list.replaceChildren(
    ...body.tools.map((t) => {
      const li = el('li');
      const params = Object.entries(t.inputSchema?.properties ?? {})
        .map(([name, p]) => `${name}: ${p.type}`)
        .join(', ');
      li.append(el('div', `${t.name}(${params})`, 'tool-name'), el('div', t.description ?? '', 'muted'));
      return li;
    }),
  );
}

async function poll() {
  try {
    const [status, calls] = await Promise.all([api('api/status'), api(`api/calls?since=${lastId}`)]);
    renderStatus(status.body);
    renderStats(calls.body.stats);
    addRows(calls.body.entries);
    if (calls.body.entries.length) lastId = calls.body.entries.at(-1).id;
  } catch (err) {
    $('status').className = 'status down';
    $('status-text').textContent = 'Monitor backend unreachable';
  }
}

$('call-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const result = $('call-result');
  result.className = 'result muted';
  result.textContent = 'Calling...';
  const { ok, body } = await postJson('api/call', { a: Number($('a').value), b: Number($('b').value) });
  result.className = `result ${ok ? 'ok' : 'err'}`;
  result.textContent = ok ? `= ${body.result}  (${body.latencyMs} ms)` : `Error: ${body.error}`;
  poll();
});

$('traffic-toggle').addEventListener('click', async () => {
  const { body } = await postJson('api/traffic', { enabled: !trafficOn, intervalMs: Number($('interval').value) });
  renderTraffic(body);
});

$('refresh-tools').addEventListener('click', loadTools);

loadTools();
poll();
setInterval(poll, POLL_MS);
