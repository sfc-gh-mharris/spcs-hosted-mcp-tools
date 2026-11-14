// Turns a tool's JSON Schema into form fields and form values back into tool arguments.
// Plain ES module with no DOM access, so Node tests can import it.

const LONG_TEXT = 200;

function kindOf(prop = {}) {
  if (Array.isArray(prop.enum)) return 'select';
  switch (prop.type) {
    case 'number':
      return 'number';
    case 'integer':
      return 'integer';
    case 'boolean':
      return 'checkbox';
    case 'string':
      return (prop.maxLength ?? Infinity) > LONG_TEXT ? 'textarea' : 'text';
    case 'array':
      return prop.items?.type === 'string' ? 'list' : 'json';
    default:
      return 'json';
  }
}

export function fieldsFor(schema) {
  const required = new Set(schema?.required ?? []);
  return Object.entries(schema?.properties ?? {}).map(([name, prop]) => ({
    name,
    kind: kindOf(prop),
    required: required.has(name),
    default: prop.default,
    options: prop.enum,
    label: prop.title ?? name,
    description: prop.description ?? '',
  }));
}

// raw holds strings from inputs (booleans for checkboxes). Returns { args } or { error }.
export function argsFrom(fields, raw) {
  const args = {};
  for (const f of fields) {
    const value = raw[f.name];
    if (f.kind === 'checkbox') {
      args[f.name] = Boolean(value);
      continue;
    }
    const text = typeof value === 'string' ? value.trim() : '';
    if (!text) {
      if (f.required) return { error: `${f.name} is required` };
      continue;
    }
    if (f.kind === 'number' || f.kind === 'integer') {
      const n = Number(text);
      if (!Number.isFinite(n)) return { error: `${f.name} must be a number` };
      if (f.kind === 'integer' && !Number.isInteger(n)) return { error: `${f.name} must be a whole number` };
      args[f.name] = n;
    } else if (f.kind === 'list') {
      args[f.name] = text.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
    } else if (f.kind === 'json') {
      try {
        args[f.name] = JSON.parse(text);
      } catch {
        return { error: `${f.name} must be valid JSON` };
      }
    } else {
      args[f.name] = typeof value === 'string' ? value : text;
    }
  }
  return { args };
}

export function summarize(value, max = 300) {
  if (value === null || value === undefined) return '-';
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > max ? `${text.slice(0, max)}…` : text;
}
