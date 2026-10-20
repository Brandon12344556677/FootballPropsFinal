/* Prop Streak Lab team dashboard: the Secret methods tab's private strategies.
   The team's private strategy rules (the unders rules and any new ones) are kept out of the public
   code: they're saved encrypted with the team password as rules.enc on the team-data branch, through
   expenses.js's window.psaTeamData, and edge_report.py (load_private) unlocks them on every update to
   grade each one in the edge tracker. Saving needs the same GitHub connection as the Expenses tab. */
(function(){
  const PATH = 'rules.enc';
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const SPORTS = {'': 'Any sport', nfl: 'NFL', nhl: 'NHL', mlb: 'MLB', nba: 'NBA'};
  // The three rules the edge tracker graded before they moved here (they're in the repo's history already).
  const ORIGINAL = [
    {key: 'mlb-unders-mid', label: 'MLB unders priced 50-65c', sport: 'mlb', side: 'under', stat: '', line: '', pmin: 0.50, pmax: 0.65},
    {key: 'nhl-assist-unders', label: 'NHL assist unders priced 65-80c', sport: 'nhl', side: 'under', stat: 'a', line: '', pmin: 0.65, pmax: 0.80},
    {key: 'mlb-tb-under', label: 'MLB total bases under 1.5', sport: 'mlb', side: 'under', stat: 'tb', line: 1.5, pmin: '', pmax: ''},
  ];
  const LISTS = {'': 'Any list', V: 'Value spots', T: 'Top 25'};
  let items = [], editing = null, busy = false;

  const msg = (t, bad) => { const m = $('prMsg'); if (m) { m.textContent = t; m.classList.toggle('bad', !!bad); } };
  const cents = v => v === '' || v == null ? '' : Math.round(v * 100);
  const has = v => v !== '' && v != null;
  const list0 = () => items;
  function describe(r){
    const bits = [SPORTS[r.sport || ''], r.side ? r.side + 's' : 'overs and unders'];
    if (r.stat) bits.push('stat "' + r.stat + '"');
    if (r.line !== '' && r.line != null) bits.push('line ' + r.line);
    if (r.pmin !== '' && r.pmin != null || r.pmax !== '' && r.pmax != null)
      bits.push('priced ' + (cents(r.pmin) === '' ? 'any' : cents(r.pmin) + '¢') + ' to ' + (cents(r.pmax) === '' ? 'any' : 'under ' + cents(r.pmax) + '¢'));
    if (r.list) bits.push(LISTS[r.list] + ' only');
    if (has(r.emin) || has(r.emax)) bits.push('model ' + (has(r.emin) ? r.emin : 'any') + ' to ' + (has(r.emax) ? 'under ' + r.emax : 'any') + ' pts over the price');
    if (r.xpos) bits.push('not ' + r.xpos);
    if (has(r.drop)) bits.push('skip if the price dropped ' + r.drop + '¢+');
    if (r.since) bits.push('added ' + r.since + ' (graded on all past picks; the record since then shows apart)');
    return bits.join(' · ');
  }
  function render(){
    $('prList').innerHTML = items.length ? items.map((r, i) =>
      `<li class="row"><span class="name">${esc(r.label)}<small>${esc(describe(r))}</small></span><span class="pct"></span>` +
      `<span class="n"><button type="button" class="ghost" data-edit="${i}">Edit</button> <button type="button" class="ghost" data-del="${i}">Delete</button></span></li>`).join('')
      : '<li class="empty">No private strategies yet.</li>';
    $('prImport').hidden = items.length > 0;
  }
  function fill(r){
    editing = r ? items.indexOf(r) : null;
    $('prLabel').value = r ? r.label : ''; $('prSport').value = r ? (r.sport || '') : ''; $('prSide').value = r ? (r.side || '') : '';
    $('prStat').value = r ? (r.stat || '') : ''; $('prLine').value = r && r.line !== '' && r.line != null ? r.line : '';
    $('prMin').value = r ? cents(r.pmin) : ''; $('prMax').value = r ? cents(r.pmax) : '';
    $('prList2').value = r ? (r.list || '') : ''; $('prEmin').value = r && has(r.emin) ? r.emin : ''; $('prEmax').value = r && has(r.emax) ? r.emax : '';
    $('prXpos').value = r ? (r.xpos || '') : ''; $('prDrop').value = r && has(r.drop) ? r.drop : '';
    $('prSave').textContent = r ? 'Save changes' : 'Add strategy';
  }
  async function save(fn, done){
    if (busy) return;
    if (!window.psaTeamData || !window.psaTeamData.canSave()) { msg('Connect GitHub in the Expenses tab (Saving from this device) to save.', true); return; }
    busy = true; msg('Saving…');
    try {
      const doc = await window.psaTeamData.update(PATH, d => { d.items = fn((d.items || []).slice()); return d; });
      items = doc.items || []; render(); msg(done || 'Saved. The edge tracker grades it from the next update (about 10 minutes).');
    } catch(e){ msg(e.status === 401 ? 'GitHub rejected the token (Expenses tab → reconnect).' : 'Couldn’t save. Check your connection and try again.', true); }
    finally { busy = false; }
  }
  async function load(){
    if (!window.psaTeamData || !window.psaTeamData.ready()) return;
    try { items = ((await window.psaTeamData.read(PATH)) || {}).items || []; render(); }
    catch(e){ msg(e.message === 'format' || e.name === 'OperationError' ? 'The saved rules don’t open with this password.' : 'Couldn’t load the private strategies.', true); }
  }
  function wire(){
    if (!$('prPanel') || $('prPanel').dataset.wired) return; $('prPanel').dataset.wired = '1';
    $('prForm').addEventListener('submit', e => {
      e.preventDefault();
      const label = $('prLabel').value.trim(); if (!label) { msg('Give the strategy a name.', true); return; }
      const num = v => v === '' ? '' : +v;
      const pmin = $('prMin').value === '' ? '' : +$('prMin').value / 100, pmax = $('prMax').value === '' ? '' : +$('prMax').value / 100;
      if (pmin !== '' && pmax !== '' && pmin >= pmax) { msg('"Price from" has to be below "price to".', true); return; }
      const rule = {key: 'private-' + label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40),
                    label, sport: $('prSport').value, side: $('prSide').value, stat: $('prStat').value.trim().toLowerCase(),
                    line: num($('prLine').value), pmin, pmax, list: $('prList2').value,
                    emin: num($('prEmin').value), emax: num($('prEmax').value),
                    xpos: $('prXpos').value.trim().toUpperCase(), drop: num($('prDrop').value)};
      const at = editing;
      // the day a rule is added: its record from then on shows apart in the Secret methods record; an edited one keeps its date
      rule.since = at != null && list0()[at] ? (list0()[at].since || '') : new Date().toLocaleDateString('en-CA', {timeZone: 'America/New_York'});
      save(list => { if (at != null && list[at]) list[at] = Object.assign({}, list[at], rule, {key: list[at].key || rule.key}); else list.push(rule); return list; })
        .then(() => fill(null));
    });
    $('prList').addEventListener('click', e => {
      const ed = e.target.closest('[data-edit]'), del = e.target.closest('[data-del]');
      if (ed) { fill(items[+ed.dataset.edit]); $('prLabel').focus(); return; }
      if (!del) return;
      if (del.dataset.sure !== '1') { del.dataset.sure = '1'; del.textContent = 'Sure?'; setTimeout(() => { if (del.isConnected) { del.dataset.sure = ''; del.textContent = 'Delete'; } }, 3000); return; }
      const i = +del.dataset.del; save(list => { list.splice(i, 1); return list; }, 'Deleted.');
    });
    $('prImport').addEventListener('click', () => save(list => list.concat(ORIGINAL), 'Added the three original unders rules.'));
    // Import methods: a pasted JSON list (from a private chat), so a set of rules never passes through the public code
    $('prPasteBtn').addEventListener('click', () => {
      let got;
      try { got = JSON.parse($('prPaste').value); } catch(e){ msg('That isn’t a list the importer can read. Paste the whole block, from [ to ].', true); return; }
      got = Array.isArray(got) ? got : (got && got.items) || [];
      const today = new Date().toLocaleDateString('en-CA', {timeZone: 'America/New_York'});
      const num = v => v === '' || v == null || isNaN(+v) ? '' : +v, str = v => v == null ? '' : String(v).trim();
      const clean = got.filter(r => r && str(r.label)).map(r => ({
        key: 'private-' + str(r.label).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40),
        label: str(r.label).slice(0, 80), sport: ['nfl', 'nba', 'nhl', 'mlb'].includes(r.sport) ? r.sport : '',
        side: ['over', 'under'].includes(r.side) ? r.side : '', stat: str(r.stat).toLowerCase().slice(0, 12), line: num(r.line),
        pmin: num(r.pmin), pmax: num(r.pmax), list: ['V', 'T'].includes(r.list) ? r.list : '', emin: num(r.emin), emax: num(r.emax),
        xpos: str(r.xpos).toUpperCase().slice(0, 20), drop: num(r.drop), since: /^\d{4}-\d\d-\d\d$/.test(str(r.since)) ? str(r.since) : today}));
      if (!clean.length) { msg('No methods with a name in what was pasted.', true); return; }
      let added = 0;
      save(list => { const have = new Set(list.map(r => (r.label || '').toLowerCase()));
        clean.forEach(r => { if (!have.has(r.label.toLowerCase())) { list.push(r); have.add(r.label.toLowerCase()); added++; } }); return list; },
        'Imported.').then(() => { if (!$('prMsg').classList.contains('bad')) { msg(`Imported ${added} method${added === 1 ? '' : 's'}` + (clean.length > added ? ` (${clean.length - added} already here, skipped)` : '') + '. They show in the record from the next update.'); $('prPaste').value = ''; } });
    });
    $('prCancel').addEventListener('click', () => { fill(null); msg(''); });
  }
  window.addEventListener('psa-unlock', () => { wire(); setTimeout(load, 300); });
  window.addEventListener('psa-lock', () => { items = []; });
})();
