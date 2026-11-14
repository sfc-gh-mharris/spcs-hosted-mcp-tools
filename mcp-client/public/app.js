// Monitor UI. Polls the backend every 2 s; all values are rendered with textContent.
import { argsFrom, fieldsFor, summarize } from './forms.js';

const POLL_MS = 2000;
const MAX_ROWS = 200;
let lastRev = 0;
let lastInboundId = 0;
let trafficOn = false;
let tools = [];
let pendingJobId = null;
const rows = new Map();

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

function badge(text, kind) {
  const cell = el('td');
  cell.append(el('span', text, `badge ${kind ?? text}`));
  return cell;
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
  $('stat-running').textContent = stats.running ?? 0;
  $('stat-errors').textContent = stats.errors;
  $('stat-avg').textContent = stats.avgMs ?? '-';
  $('stat-p95').textContent = stats.p95Ms ?? '-';
}

function statusText(e) {
  if (e.status === 'running') return 'running...';
  return e.ok ? 'ok' : `${e.errorKind}: ${e.error}`;
}

function cell(value, max) {
  const text = summarize(value, max);
  const td = el('td', text, 'mono');
  const full = summarize(value, 4000);
  if (full !== text) td.title = full;
  return td;
}

function fillRow(row, e) {
  row.className = e.status === 'running' ? 'running' : e.ok ? '' : 'err';
  row.replaceChildren(
    el('td', String(e.id), 'num'),
    el('td', new Date(e.ts).toLocaleTimeString()),
    badge(e.source),
    el('td', e.tool, 'mono nowrap'),
    cell(e.args, 80),
    e.status === 'done' && e.ok ? cell(e.result, 160) : el('td', '-'),
    el('td', e.latencyMs === undefined ? '-' : String(e.latencyMs), 'num'),
    el('td', statusText(e)),
  );
}

function upsertRows(entries) {
  const tbody = $('log');
  for (const e of entries) {
    let row = rows.get(e.id);
    if (!row) {
      row = el('tr');
      rows.set(e.id, row);
      tbody.prepend(row);
    }
    fillRow(row, e);
    if (e.id === pendingJobId && e.status === 'done') showResult(e);
  }
  while (tbody.rows.length > MAX_ROWS) {
    const last = tbody.rows[tbody.rows.length - 1];
    rows.delete(Number(last.cells[0].textContent));
    last.remove();
  }
}

function addInboundRows(entries) {
  const tbody = $('inbound');
  for (const e of entries) {
    const row = el('tr', undefined, e.ok ? '' : 'err');
    row.append(
      el('td', String(e.id), 'num'),
      el('td', new Date(e.ts).toLocaleTimeString()),
      badge(e.endpoint),
      el('td', e.caller ?? '-'),
      el('td', e.tool ?? '-', 'mono nowrap'),
      cell(e.args, 80),
      e.ok ? cell(e.result, 160) : el('td', '-'),
      el('td', String(e.latency_ms), 'num'),
      el('td', e.ok ? 'ok' : e.error ?? 'error'),
    );
    tbody.prepend(row);
  }
  while (tbody.rows.length > MAX_ROWS) tbody.deleteRow(-1);
}

function showResult(e) {
  pendingJobId = null;
  const result = $('call-result');
  result.className = `result ${e.ok ? 'ok' : 'err'}`;
  result.textContent = e.ok ? `${summarize(e.result, 2000)}  (${e.latencyMs} ms)` : `Error: ${e.error}`;
}

// --- tool selection and generated form ---

function selectedTool() {
  return tools.find((t) => t.name === $('tool-select').value);
}

function inputFor(field) {
  const id = `field-${field.name}`;
  let input;
  if (field.kind === 'select') {
    input = el('select');
    for (const option of field.options) input.append(el('option', option));
    if (field.default !== undefined) input.value = field.default;
  } else if (field.kind === 'textarea' || field.kind === 'list' || field.kind === 'json') {
    input = el('textarea');
    input.rows = field.kind === 'textarea' ? 4 : 2;
    input.placeholder = field.kind === 'list' ? 'one per line or comma separated' : field.kind === 'json' ? 'JSON' : '';
  } else if (field.kind === 'checkbox') {
    input = el('input');
    input.type = 'checkbox';
    input.checked = Boolean(field.default);
  } else {
    input = el('input');
    input.type = field.kind === 'text' ? 'text' : 'number';
    if (field.kind === 'number') input.step = 'any';
    if (field.default !== undefined) input.placeholder = `default ${field.default}`;
  }
  input.id = id;
  input.dataset.field = field.name;
  const label = el('label', `${field.name}${field.required ? ' *' : ''}`);
  label.htmlFor = id;
  const wrap = el('div', undefined, 'field');
  wrap.append(label, input);
  if (field.description) wrap.append(el('span', field.description, 'hint'));
  return wrap;
}

function renderForm() {
  const tool = selectedTool();
  $('tool-description').textContent = tool?.description ?? '';
  const fields = tool ? fieldsFor(tool.inputSchema) : [];
  $('tool-fields').replaceChildren(...(fields.length ? fields.map(inputFor) : [el('p', 'No parameters.', 'muted')]));
  if (tool?.name === 'add') {
    $('field-a').value = '2';
    $('field-b').value = '3';
  }
}

function chooseTool(name) {
  $('tool-select').value = name;
  renderForm();
}

async function loadTools() {
  const list = $('tools');
  list.replaceChildren(el('li', 'Loading...', 'muted'));
  const { ok, body } = await api('api/tools');
  if (!ok) {
    list.replaceChildren(el('li', `Could not list tools: ${body.error ?? 'unknown error'}`, 'muted'));
    return;
  }
  const previous = $('tool-select').value;
  tools = body.tools;
  list.replaceChildren(
    ...tools.map((t) => {
      const li = el('li', undefined, 'clickable');
      const params = Object.entries(t.inputSchema?.properties ?? {})
        .map(([name, p]) => `${name}: ${p.type ?? 'any'}`)
        .join(', ');
      li.append(el('div', `${t.name}(${params})`, 'tool-name'), el('div', t.description ?? '', 'muted'));
      li.addEventListener('click', () => chooseTool(t.name));
      return li;
    }),
  );
  $('tool-select').replaceChildren(...tools.map((t) => el('option', t.name)));
  chooseTool(tools.some((t) => t.name === previous) ? previous : tools[0]?.name ?? '');
}

// --- polling ---

async function poll() {
  try {
    const [status, calls] = await Promise.all([api('api/status'), api(`api/calls?sinceRev=${lastRev}`)]);
    renderStatus(status.body);
    renderStats(calls.body.stats);
    upsertRows(calls.body.entries);
    lastRev = Math.max(lastRev, calls.body.stats.lastRev ?? 0);
  } catch {
    $('status').className = 'status down';
    $('status-text').textContent = 'Monitor backend unreachable';
  }
  try {
    const inbound = await api(`api/inbound?since=${lastInboundId}`);
    $('inbound-error').hidden = inbound.ok;
    if (inbound.ok) {
      addInboundRows(inbound.body.entries);
      if (inbound.body.entries.length) lastInboundId = inbound.body.entries.at(-1).id;
    } else {
      $('inbound-error').textContent = `Could not read the server call log: ${inbound.body.error ?? inbound.status}`;
    }
  } catch {
    /* status already shows the backend as unreachable */
  }
}

$('call-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const tool = selectedTool();
  if (!tool) return;
  const raw = {};
  for (const input of $('tool-fields').querySelectorAll('[data-field]')) {
    raw[input.dataset.field] = input.type === 'checkbox' ? input.checked : input.value;
  }
  const result = $('call-result');
  const { args, error } = argsFrom(fieldsFor(tool.inputSchema), raw);
  if (error) {
    result.className = 'result err';
    result.textContent = error;
    return;
  }
  result.className = 'result muted';
  result.textContent = `Running ${tool.name}...`;
  const { ok, body } = await postJson('api/jobs', { tool: tool.name, args });
  if (!ok) {
    result.className = 'result err';
    result.textContent = `Error: ${body.error}`;
    return;
  }
  pendingJobId = body.entry.id;
  poll();
});

$('tool-select').addEventListener('change', renderForm);

$('traffic-toggle').addEventListener('click', async () => {
  const { body } = await postJson('api/traffic', { enabled: !trafficOn, intervalMs: Number($('interval').value) });
  renderTraffic(body);
});

$('refresh-tools').addEventListener('click', loadTools);

for (const tab of document.querySelectorAll('.tab')) {
  tab.addEventListener('click', () => {
    for (const other of document.querySelectorAll('.tab')) {
      const active = other === tab;
      other.classList.toggle('active', active);
      other.setAttribute('aria-selected', String(active));
      $(`tab-${other.dataset.tab}`).hidden = !active;
    }
  });
}

loadTools();
poll();
setInterval(poll, POLL_MS);
