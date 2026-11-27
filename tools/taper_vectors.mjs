// SPDX-License-Identifier: GPL-3.0-only
// Regenerates tests/data/taper_vectors.json from the lab's own taper maths.
// The three functions below are copied, types removed, from lab
// apps/studio/src/modules/registry.ts at LAB_PIN (95553fe). Run: node tools/taper_vectors.mjs
import { readFileSync, writeFileSync } from 'node:fs';
const clamp01 = (n) => Math.min(1, Math.max(0, n));
function quantize(p, v) {
  let x = Math.min(p.maximum, Math.max(p.minimum, v));
  if (p.step && p.step > 0) x = Math.round((x - p.minimum) / p.step) * p.step + p.minimum;
  return Math.min(p.maximum, Math.max(p.minimum, x));
}
function normToValue(p, n) {
  const t = clamp01(n); let v;
  if (p.taper === 'log' && p.minimum > 0 && p.maximum > 0) v = p.minimum * Math.pow(p.maximum / p.minimum, t);
  else v = p.minimum + (p.maximum - p.minimum) * t;
  return quantize(p, v);
}
function valueToNorm(p, v) {
  const x = Math.min(p.maximum, Math.max(p.minimum, v));
  if (p.taper === 'log' && p.minimum > 0 && p.maximum > 0) return clamp01(Math.log(x / p.minimum) / Math.log(p.maximum / p.minimum));
  const span = p.maximum - p.minimum; return span === 0 ? 0 : clamp01((x - p.minimum) / span);
}
const cat = JSON.parse(readFileSync(new URL('../tests/data/catalogue.json', import.meta.url)));
const norms = [-0.1, 0, 0.1, 0.25, 0.333, 0.5, 0.77, 1, 1.2];
const rows = [];
for (const m of cat.modules) for (const p of m.parameters) {
  const values = [p.minimum, p.default, p.maximum, (p.minimum + p.maximum) / 2, p.minimum - 1, p.maximum + 1];
  rows.push({ module: m.id, param: p.id,
    n2v: norms.map((n) => [n, normToValue(p, n)]),
    v2n: values.map((v) => [v, valueToNorm(p, v)]) });
}
writeFileSync(new URL('../tests/data/taper_vectors.json', import.meta.url),
  JSON.stringify({ 'SPDX-License-Identifier': 'GPL-3.0-only', _source: cat._source, rows }) + '\n');
console.log(rows.length, 'parameters');
