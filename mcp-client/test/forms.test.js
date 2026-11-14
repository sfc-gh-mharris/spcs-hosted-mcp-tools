import { test } from 'node:test';
import assert from 'node:assert/strict';
import { argsFrom, fieldsFor, summarize } from '../public/forms.js';

// Shapes copied from the Python server's tools/list.
const COMPLETE = {
  type: 'object',
  properties: {
    prompt: { description: 'The prompt to send', maxLength: 8000, minLength: 1, title: 'Prompt', type: 'string' },
    model: { default: 'claude-haiku-4-5', enum: ['claude-haiku-4-5', 'llama3.3-70b'], title: 'Model', type: 'string' },
    max_tokens: { default: 1024, maximum: 4096, minimum: 1, title: 'Max Tokens', type: 'integer' },
  },
  required: ['prompt'],
};
const CLASSIFY = {
  type: 'object',
  properties: {
    text: { maxLength: 8000, type: 'string' },
    categories: { items: { type: 'string' }, minItems: 2, maxItems: 20, type: 'array' },
  },
  required: ['text', 'categories'],
};
const ADD = { type: 'object', properties: { a: { type: 'number' }, b: { type: 'number' } }, required: ['a', 'b'] };

test('fieldsFor maps schema types to input kinds', () => {
  const fields = fieldsFor(COMPLETE);
  assert.deepEqual(
    fields.map((f) => [f.name, f.kind, f.required]),
    [['prompt', 'textarea', true], ['model', 'select', false], ['max_tokens', 'integer', false]],
  );
  assert.deepEqual(fields[1].options, ['claude-haiku-4-5', 'llama3.3-70b']);
  assert.equal(fields[1].default, 'claude-haiku-4-5');
  assert.equal(fieldsFor(CLASSIFY)[1].kind, 'list');
  assert.equal(fieldsFor(ADD)[0].kind, 'number');
});

test('short strings get a text input, unknown shapes get JSON', () => {
  const fields = fieldsFor({ properties: { name: { type: 'string', maxLength: 50 }, opts: { type: 'object' } } });
  assert.deepEqual(fields.map((f) => f.kind), ['text', 'json']);
});

test('tools without parameters produce no fields', () => {
  assert.deepEqual(fieldsFor({ type: 'object', properties: {} }), []);
  assert.deepEqual(fieldsFor(undefined), []);
});

test('argsFrom converts numbers, lists, and skips empty optional fields', () => {
  const fields = fieldsFor(COMPLETE);
  assert.deepEqual(argsFrom(fields, { prompt: 'hi', model: 'llama3.3-70b', max_tokens: '' }), {
    args: { prompt: 'hi', model: 'llama3.3-70b' },
  });
  assert.deepEqual(argsFrom(fieldsFor(ADD), { a: '2.5', b: '-3' }), { args: { a: 2.5, b: -3 } });
  assert.deepEqual(argsFrom(fieldsFor(CLASSIFY), { text: 't', categories: 'billing, shipping\nreturns\n' }), {
    args: { text: 't', categories: ['billing', 'shipping', 'returns'] },
  });
});

test('argsFrom reports missing required fields and bad numbers', () => {
  assert.match(argsFrom(fieldsFor(ADD), { a: '1', b: '' }).error, /b is required/);
  assert.match(argsFrom(fieldsFor(ADD), { a: 'x', b: '1' }).error, /a must be a number/);
  assert.match(argsFrom(fieldsFor(COMPLETE), { prompt: 'p', max_tokens: '1.5' }).error, /max_tokens must be a whole number/);
  assert.match(argsFrom(fieldsFor({ properties: { o: { type: 'object' } } }), { o: '{bad' }).error, /o must be valid JSON/);
});

test('summarize keeps short values and truncates long ones', () => {
  assert.equal(summarize(42), '42');
  assert.equal(summarize('hello'), 'hello');
  assert.equal(summarize({ label: 'billing' }), '{"label":"billing"}');
  assert.equal(summarize(null), '-');
  const long = summarize('x'.repeat(500), 100);
  assert.equal(long.length, 101);
  assert.ok(long.endsWith('…'));
});
