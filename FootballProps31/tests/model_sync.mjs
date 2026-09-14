// Proves the JavaScript model in template.html matches the Python model in build.py.
// Run the Python tests first (they write tests/model_cases.json), then:  node tests/model_sync.mjs
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, '..', 'template.html'), 'utf8');
const m = html.match(/\/\/ ==== MODEL[\s\S]*?\n([\s\S]*?)\/\/ ==== END MODEL/);
if (!m) { console.error('MODEL block not found in template.html'); process.exit(1); }
const api = new Function(m[1] + '\nreturn {MODEL, CTX, modelProb, seedLine, gradeResult, sideProb, ncdf, contextScale, histContext, statFamily, defStatFor};')();

const doc = JSON.parse(readFileSync(join(here, 'model_cases.json'), 'utf8'));
let bad = 0;
const tol = 1e-9;
for (const c of doc.model) {
  const got = api.modelProb(c.values, c.line, c.kind, c.scale);
  for (const k of ['over', 'under', 'push', 'lo', 'hi', 'neff', 'mean', 'sd', 'h', 'scale']) {
    if (Math.abs(got[k] - c.expect[k]) > tol) { bad++; console.error(`mismatch ${k}: js=${got[k]} py=${c.expect[k]} for`, c.values, c.line, c.scale); }
  }
  if (got.n !== c.expect.n) { bad++; console.error('n mismatch'); }
  if (api.seedLine(c.values) !== c.seed) { bad++; console.error(`seed mismatch js=${api.seedLine(c.values)} py=${c.seed}`); }
}
for (const key of ['betaPts', 'betaSpr', 'gamma']) for (const fam of ['pass', 'rush', 'rec'])
  if (api.CTX[key][fam] !== doc.CTX[key][fam]) { bad++; console.error(`CTX.${key}.${fam} differs: js=${api.CTX[key][fam]} py=${doc.CTX[key][fam]}`); }
for (const key of Object.keys(doc.MODEL)) if (api.MODEL[key] !== doc.MODEL[key]) { bad++; console.error(`MODEL.${key} differs`); }
const hist = api.histContext(doc.hist.rows);
for (const k of ['pts', 'spr']) if (Math.abs((hist[k] ?? -1) - (doc.hist.expect[k] ?? -1)) > tol) { bad++; console.error(`histContext ${k} mismatch`, hist, doc.hist.expect); }
for (const c of doc.ctx) {
  const got = api.contextScale(c.fam, c.hist, c.gamePts, c.gameSpr, c.defRatio);
  for (const k of ['scale', 'env', 'def']) if (Math.abs(got[k] - c.expect[k]) > tol) { bad++; console.error(`contextScale ${k} mismatch`, c, got); }
}
if (api.statFamily('rush_rec_yds', 'WR') !== 'rec' || api.defStatFor('scrim_td', 'RB') !== 'rush_td') { bad++; console.error('family/defStat mismatch'); }
if (api.gradeResult(70, 60.5, 'over') !== 'hit' || api.gradeResult(60, 60, 'over') !== 'push') { bad++; console.error('gradeResult mismatch'); }
if (bad) { console.error(`${bad} mismatch(es)`); process.exit(1); }
console.log(`JS model matches Python on ${doc.model.length} model cases + ${doc.ctx.length} context cases (tolerance ${tol}).`);
