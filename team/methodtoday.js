/* Prop Streak Lab team dashboard: the Secret methods tab's "Today's picks" panel. For each private
   method (rules.js's rules, unlocked in the browser), the picks on today's ET slate that fit it, read
   from the public picks files (nhl/mlb/nba_picks_recent.json; NFL from picks.json with kickoffs from
   data.json, loaded only on an NFL game day when a method can take NFL), followed live through
   parlaylive.js (each pick is tracked as a one-leg "parlay"). The fit test mirrors edge_report.py's
   rule_test and graded() price checks, so these are the picks the edge tracker will grade for that
   method. A pending pick's price can still move until it locks shortly before its game, so a pick can
   join or drop off a method until then. Display only. */
(function(){
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const SPN = {nfl: 'NFL', nba: 'NBA', nhl: 'NHL', mlb: 'MLB'};
  const RES = {hit: '✅ Hit', miss: '❌ Miss', push: 'Push', dnp: 'DNP', void: 'Void'};
  const RECENT = {nhl: '../nhl_picks_recent.json', mlb: '../mlb_picks_recent.json', nba: '../nba_picks_recent.json'};
  const RELOAD_MS = 5 * 60 * 1000;
  const etDay = t => new Date(t).toLocaleDateString('en-CA', {timeZone: 'America/New_York'});
  const frac = x => x == null || x === '' || isNaN(+x) ? null : (+x > 1 ? +x / 100 : +x);
  const num = v => v == null || v === '' || isNaN(+v) ? null : +v;
  let rules = [], picks = null, at = 0, busy = false, on = false;
  const tracked = new Set();   // parlaylive roots in use: each is stopped before its table goes away

  async function getJSON(u){
    const r = await fetch(u + '?t=' + Date.now(), {cache: 'no-store'});
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }
  const rowsOf = d => (d && d.cols ? (d.picks || []).map(r => Object.fromEntries(d.cols.map((c, i) => [c, r[i]]))) : []);

  // An ET wall-clock date + time ("2026-10-22", "20:15") as an ISO UTC string.
  function etISO(date, time){
    const guess = new Date(`${date}T${time}:00Z`);
    const wall = new Date(guess.toLocaleString('en-US', {timeZone: 'America/New_York'}));
    const utc = new Date(guess.toLocaleString('en-US', {timeZone: 'UTC'}));
    return new Date(guess.getTime() + (utc - wall)).toISOString();
  }

  // A picks-file row as the edge tracker sees it (edge_report.graded), or null if it can't be graded.
  function shape(sport, p){
    if (p.src !== 'live') return null;
    const pr = frac(p.price), p0 = frac(p.px0);
    if (pr == null || pr < 0.10 || pr > 0.99 || (p0 != null && Math.abs(pr - p0) > 0.35)) return null;
    return {sport, pr, p0, prob: p.prob, side: p.side || 'over', stat: p.stat, line: p.line, lists: p.lists || '', pos: p.pos,
            player: p.player, team: p.team, opp: p.opp, pid: p.pid, gid: p.gid, start: p.start, res: p.res || null};
  }

  // edge_report.rule_test, without "since" (today is always after a method was added).
  function fits(r, p){
    const sport = r.sport || null, side = r.side || null, stat = r.stat || null;
    const line = num(r.line), lo = num(r.pmin), hi = num(r.pmax), lst = r.list || null;
    const emin = num(r.emin), emax = num(r.emax), drop = num(r.drop);
    const xpos = new Set(String(r.xpos || '').split(',').map(x => x.trim().toUpperCase()).filter(Boolean));
    if (sport && p.sport !== sport) return false;
    if (side && p.side !== side) return false;
    if (stat && p.stat !== stat) return false;
    if (line != null && p.line !== line) return false;
    if ((lo != null && p.pr < lo) || (hi != null && p.pr >= hi)) return false;
    if (lst && !p.lists.includes(lst)) return false;
    if (xpos.size && xpos.has(String(p.pos || '').toUpperCase())) return false;
    if (emin != null || emax != null){
      if (p.prob == null) return false;
      const edge = (p.prob - p.pr) * 100;
      if ((emin != null && edge < emin) || (emax != null && edge >= emax)) return false;
    }
    if (drop != null && p.p0 != null && Math.round((p.pr - p.p0) * 100) <= -drop) return false;
    return true;
  }

  async function loadPicks(){
    const today = etDay(Date.now()), out = [];
    const sports = new Set(rules.map(r => r.sport || ''));
    const want = s => sports.has('') || sports.has(s);
    await Promise.all(Object.entries(RECENT).filter(([s]) => want(s)).map(async ([s, url]) => {
      try { rowsOf(await getJSON(url)).forEach(p => { const q = p.start && etDay(p.start) === today && shape(s, p); if (q) out.push(q); }); }
      catch(e){}
    }));
    if (want('nfl')) try {
      const kick = {};
      (((await getJSON('../data.json')).week || {}).games || []).forEach(g => { if (g.date === today && g.time) kick[g.id] = etISO(g.date, g.time); });
      if (Object.keys(kick).length)
        rowsOf(await getJSON('../picks.json')).forEach(p => { if (kick[p.gid]){ const q = shape('nfl', Object.assign({}, p, {start: kick[p.gid]})); if (q) out.push(q); } });
    } catch(e){}
    out.sort((a, b) => (a.start || '').localeCompare(b.start || '') || String(a.player).localeCompare(String(b.player)));
    return out;
  }

  function render(){
    const box = $('smToday'); if (!box) return;
    if (!rules.length){ box.innerHTML = '<p class="empty">No private methods yet: add one under Private strategies.</p>'; return; }
    if (!picks){ box.innerHTML = '<p class="empty">Loading today’s picks…</p>'; return; }
    const when = s => { const t = Date.parse(s); return isFinite(t) ? new Date(t).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'}) : ''; };
    const groups = rules.map((r, k) => ({r, k, list: picks.filter(p => fits(r, p))}));
    box.innerHTML = groups.map(({r, k, list}) => {
      const hit = list.filter(p => p.res === 'hit').length, miss = list.filter(p => p.res === 'miss').length, open = list.filter(p => !p.res).length;
      const units = list.reduce((s, p) => s + (p.res === 'hit' ? 1 / p.pr - 1 : p.res === 'miss' ? -1 : 0), 0);
      const sum = list.length ? `${list.length} pick${list.length === 1 ? '' : 's'}` + (hit ? ` · ${hit} hit` : '') + (miss ? ` · ${miss} missed` : '') +
        (open ? ` · ${open} to go` : '') + (hit || miss ? ` · ${units >= 0 ? '+' : '−'}${Math.abs(units).toFixed(2)}u so far` : '') : 'No picks today';
      const rows = list.map((p, i) => `<tr class="pl-card sm-pk" data-pl="${i}"><td>${esc(when(p.start))}</td><td>${esc(SPN[p.sport] || p.sport)} · <b>${esc(p.player)}</b> <small>${esc(p.team)} vs ${esc(p.opp)}</small></td>` +
        `<td>${esc(p.side)} ${esc(p.line)} ${esc(p.stat)}</td><td class="n">${Math.round(p.pr * 100)}¢</td><td class="n">${p.prob == null ? '–' : Math.round(p.prob * 100) + '%'}</td>` +
        `<td data-leg="0"><span class="pl-live"></span></td><td>${p.res ? RES[p.res] || esc(p.res) : 'Pending'}</td></tr>`).join('');
      return `<details class="plpast sm-day"${list.length ? ' open' : ''}><summary><span>${esc(r.label)}</span><span class="label">${esc(sum)}</span></summary>` +
        (list.length ? `<p class="hint" id="smN${k}"></p><div class="edwrap"><table class="edges pst"><thead><tr><th>Starts</th><th>Player</th><th>Bet</th><th class="n">Price</th><th class="n">Model</th><th>Live</th><th>Result</th></tr></thead>` +
          `<tbody id="smT${k}">${rows}</tbody></table></div>` : '') + '</details>';
    }).join('');
    untrack();
    if (window.psaParlayLive) groups.forEach(({k, list}) => {
      if (!list.length) return;
      tracked.add(k);
      window.psaParlayLive.track(list.map(p => ({legs: [p], res: p.res})), {root: 'smT' + k, note: 'smN' + k});
    });
    $('smTodayUpd').textContent = 'Team only · picks as of ' + new Date(at).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'});
  }

  function untrack(){
    if (window.psaParlayLive) tracked.forEach(k => window.psaParlayLive.track([], {root: 'smT' + k, note: 'smN' + k}));
    tracked.clear();
  }

  async function refresh(force){
    if (!on || busy || (!force && Date.now() - at < RELOAD_MS - 5000)) return;
    busy = true;
    try { picks = await loadPicks(); at = Date.now(); render(); }
    finally { busy = false; }
  }

  window.addEventListener('psa-rules', e => { on = true; rules = (e.detail || []).filter(r => r && r.label); render(); refresh(true); });
  window.addEventListener('psa-refresh', () => refresh(false));
  setInterval(() => refresh(false), RELOAD_MS);
  window.addEventListener('psa-lock', () => { untrack(); on = false; rules = []; picks = null; at = 0; const b = $('smToday'); if (b) b.innerHTML = ''; });
  window.psaMethodToday = {_fits: fits, _shape: shape, _etISO: etISO};
})();
