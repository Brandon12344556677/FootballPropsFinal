/* Prop Streak Lab team dashboard: the Secret methods tab's private strategies and Today's matches.
   The team's private strategy rules (the unders rules and any new ones) are kept out of the public
   code: they're saved encrypted with the team password as rules.enc on the team-data branch, through
   expenses.js's window.psaTeamData, and edge_report.py (load_private) unlocks them on every update to
   grade each one in the edge tracker. Saving needs the same GitHub connection as the Expenses tab.
   Today's matches applies each rule (decrypted here, never in the public code) to the upcoming picks in
   the public *_picks_recent.json files, and flags a pick whose price fell by the rule's "skip if it
   dropped" amount from its first price. The tests mirror edge_report.rule_test. */
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
  const STAT = {g: 'goals', a: 'assists', pts: 'points', sog: 'shots', reb: 'rebounds', ast: 'assists', tpm: 'threes', pra: 'pts+reb+ast',
    tb: 'total bases', h: 'hits', hrr: 'hits+runs+RBIs', k: 'strikeouts', rbi: 'RBIs', hr: 'home runs', pass_yds: 'passing yards',
    rush_yds: 'rushing yards', rec_yds: 'receiving yards', rec: 'receptions'};
  const FEEDS = [['nhl', '../nhl_picks_recent.json'], ['nba', '../nba_picks_recent.json'], ['mlb', '../mlb_picks_recent.json']];
  let items = [], editing = null, busy = false, upcoming = [];

  const msg = (t, bad) => { const m = $('prMsg'); if (m) { m.textContent = t; m.classList.toggle('bad', !!bad); } };
  const cents = v => v === '' || v == null ? '' : Math.round(v * 100);
  const has = v => v !== '' && v != null;
  const list0 = () => items;
  // edge_report.rule_test, without the price-drop part (Today's matches shows that as a flag)
  function fits(r, p){
    if (r.sport && p.sport !== r.sport || r.side && p.side !== r.side || r.stat && p.stat !== r.stat) return false;
    if (has(r.line) && +p.line !== +r.line || has(r.pmin) && p.pr < r.pmin || has(r.pmax) && p.pr >= r.pmax) return false;
    if (r.list && !(p.lists || '').includes(r.list)) return false;
    const xpos = String(r.xpos || '').split(',').map(x => x.trim().toUpperCase()).filter(Boolean);
    if (xpos.length && xpos.includes(String(p.pos || '').toUpperCase())) return false;
    if (has(r.emin) || has(r.emax)) {
      if (p.prob == null) return false;
      const e = (p.prob - p.pr) * 100;
      if (has(r.emin) && e < r.emin || has(r.emax) && e >= r.emax) return false;
    }
    return true;
  }
  const dropped = (r, p) => has(r.drop) && p.p0 != null && Math.round((p.pr - p.p0) * 100) <= -r.drop;   // whole cents: 47c -> 44c is -3
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
    bits.push(r.since ? 'graded from ' + r.since : 'graded on all picks');
    return bits.join(' · ');
  }
  function render(){
    $('prList').innerHTML = items.length ? items.map((r, i) =>
      `<li class="row"><span class="name">${esc(r.label)}<small>${esc(describe(r))}</small></span><span class="pct"></span>` +
      `<span class="n"><button type="button" class="ghost" data-edit="${i}">Edit</button> <button type="button" class="ghost" data-del="${i}">Delete</button></span></li>`).join('')
      : '<li class="empty">No private strategies yet.</li>';
    $('prImport').hidden = items.length > 0;
    matches();
  }
  // ---- Today's matches: each rule against the upcoming picks ----
  const frac = v => v == null ? null : (+v > 1 ? +v / 100 : +v);
  async function loadUpcoming(){
    const now = Date.now(), out = [];
    await Promise.all(FEEDS.map(async ([sport, url]) => {
      try {
        const d = await fetch(url + '?t=' + now, {cache: 'no-store'}).then(r => r.ok ? r.json() : null);
        (d && d.picks || []).forEach(row => {
          const p = {}; d.cols.forEach((c, i) => { p[c] = row[i]; });
          const t = Date.parse(p.start);
          if (p.src !== 'live' || p.res != null || !(t > now)) return;
          p.pr = frac(p.price); p.p0 = frac(p.px0);
          if (p.pr == null || p.pr < 0.10 || p.pr > 0.99) return;
          if (p.p0 != null && (Math.abs(p.pr - p.p0) > 0.35 || p.p0 < 0.10 || p.p0 > 0.99)) p.p0 = null;
          p.sport = sport; out.push(p);
        });
      } catch(e){}
    }));
    upcoming = out; matches();
  }
  function matches(){
    const el = $('smMatches'); if (!el) return;
    if (!items.length) { el.innerHTML = '<p class="empty">Add a strategy below and its upcoming picks show up here.</p>'; return; }
    const when = s => new Date(s).toLocaleString('en-US', {weekday: 'short', hour: 'numeric', minute: '2-digit'});
    el.innerHTML = items.map(r => {
      const ps = upcoming.filter(p => fits(r, p)).sort((a, b) => a.start.localeCompare(b.start) || (b.prob - b.pr) - (a.prob - a.pr));
      const bet = ps.filter(p => !dropped(r, p)).length;
      const rows = ps.map(p => { const mv = p.p0 == null ? null : Math.round((p.pr - p.p0) * 100), skip = dropped(r, p);
        return `<tr class="${skip ? 'sm-skip' : ''}"><td>${esc(p.sport.toUpperCase())} · <b>${esc(p.player)}</b> <small>${esc(p.team)} vs ${esc(p.opp)}${p.pos ? ' · ' + esc(p.pos) : ''}</small></td>` +
          `<td>${esc(p.side)} ${esc(p.line)} ${esc(STAT[p.stat] || p.stat)}${(p.lists || '').includes('V') ? ' <span class="chip">Value</span>' : (p.lists || '').includes('T') ? ' <span class="chip">Top 25</span>' : ''}</td>` +
          `<td class="n">${p.p0 == null ? '–' : Math.round(p.p0 * 100) + '¢'} → <b>${Math.round(p.pr * 100)}¢</b>${mv ? ` <small class="${mv < 0 ? 'down' : 'up'}">${mv > 0 ? '+' : ''}${mv}</small>` : ''}</td>` +
          `<td class="n">${p.prob == null ? '–' : Math.round(p.prob * 100) + '%'}</td><td>${when(p.start)}</td>` +
          `<td>${skip ? `<span class="chip bad">Skip: down ${-mv}¢</span>` : '<span class="chip do">Fits</span>'}</td></tr>`; }).join('');
      return `<h3 class="subh">${esc(r.label)} <span class="label">${ps.length ? `${bet} to bet${ps.length > bet ? ` · ${ps.length - bet} skip` : ''}` : 'nothing upcoming'}</span></h3>` +
        (ps.length ? `<div class="edwrap"><table class="edges pst"><thead><tr><th>Player</th><th>Pick</th><th class="n">First → now</th><th class="n">Model</th><th>Starts</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : '');
    }).join('') + '<p class="hint" style="margin-top:8px">Upcoming NHL, NBA and MLB picks (NFL isn\u2019t in the recent-picks feed). Prices refresh with each site update, about every 10 minutes; check the exchange before betting.</p>';
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
      // a new rule is graded only on picks from today on (it was likely found on the past ones); an edited one keeps its date
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
    $('prCancel').addEventListener('click', () => { fill(null); msg(''); });
  }
  window.addEventListener('psa-unlock', () => { wire(); setTimeout(load, 300); loadUpcoming(); });
  window.addEventListener('psa-refresh', () => { loadUpcoming(); });
  window.addEventListener('psa-lock', () => { items = []; });
})();
