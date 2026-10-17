/* Live tracker for today's model parlays (dashboard's Model parlays panel). parlays.enc only changes
   every update pass (~10 minutes) and a leg is graded only once its sport's builder sees the final box
   score, so this reads ESPN's public scoreboards and box scores straight from the browser (they allow
   it) every 30 seconds while the tab is open and a leg is still in play: each leg's current number
   against its line, its game clock, and whether the parlay is still alive. Display only: the record
   is still parlay.py's grading. NHL, MLB and NBA players match on ESPN's player id (the builders use
   ESPN's); NFL picks carry nflverse ids, so those match on name and team.
   Index: window.psaParlayLive.track(parlays) after the panel renders; cards carry data-pl, legs data-leg. */
(function(){
  const POLL_MS = 30000;
  const PATH = {nfl: 'football/nfl', nba: 'basketball/nba', nhl: 'hockey/nhl', mlb: 'baseball/mlb'};
  const API = 'https://site.web.api.espn.com/apis/site/v2/sports/';
  const NFL_ALIAS = {LAR: 'LA', WSH: 'WAS', JAC: 'JAX'};   // build.py TEAM_ALIAS: ESPN code -> ours
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const etDate = s => new Date(s).toLocaleDateString('en-CA', {timeZone: 'America/New_York'}).replace(/-/g, '');
  const team = (sport, t) => sport === 'nfl' ? (NFL_ALIAS[t] || t) : String(t || '').toUpperCase();
  const pkey = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[.'`-]/g, '').replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '').replace(/\s+/g, ' ').trim();
  const num = v => { const n = parseFloat(String(v ?? '').split(/[-/]/)[0]); return isFinite(n) ? n : 0; };
  const second = v => { const n = parseFloat(String(v ?? '').split(/[-/]/)[1]); return isFinite(n) ? n : 0; };
  const outs = ip => { const [w, p] = String(ip || '0').split('.'); return (parseInt(w) || 0) * 3 + (parseInt(p) || 0); };

  let parlays = [], timer = null, updated = null;
  const boards = {};    // `${sport}|${yyyymmdd}` -> {at, events}
  const boxes = {};     // `${sport}|${eventId}` -> {final, players: {id: athlete}, byName: {team|name: athlete}}

  async function getJSON(url){
    const r = await fetch(url, {cache: 'no-store'});
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }

  // One ESPN summary -> every player's numbers, keyed by category ("passing.passingYards", "batting.hits").
  function parseBox(sport, s){
    const players = {}, byName = {};
    const xb = {};      // MLB doubles/triples per batter from the play-by-play, as build_mlb.py parse_box
    if (sport === 'mlb') for (const pl of s.plays || []){
      const t = ((pl.type || {}).text || '').trim().toLowerCase();
      const k = t === 'double' || t === 'ground rule double' ? 0 : t === 'triple' ? 1 : null;
      const bat = k == null ? null : ((pl.participants || []).find(p => p.type === 'batter') || {}).athlete;
      if (bat && bat.id) (xb[bat.id] = xb[bat.id] || [0, 0])[k]++;
    }
    const steals = {};
    if (sport === 'mlb') for (const ro of s.rosters || []) for (const e of ro.roster || [])
      for (const st of e.stats || []) if (st.name === 'stolenBases') steals[(e.athlete || {}).id] = num(st.value ?? st.displayValue);
    for (const tb of (s.boxscore || {}).players || []){
      const ab = team(sport, (tb.team || {}).abbreviation);
      for (const cat of tb.statistics || []){
        const name = cat.type || cat.name || 'stats', keys = cat.keys || [];
        for (const a of cat.athletes || []){
          const info = a.athlete || {}, id = String(info.id || '');
          if (!id) continue;
          const p = players[id] = players[id] || {id, name: info.displayName, team: ab, dnp: false, s: {}};
          if (a.didNotPlay || !(a.stats || []).length){ p.dnp = p.dnp || !!a.didNotPlay; continue; }
          keys.forEach((k, i) => { p.s[name + '.' + k] = a.stats[i]; });
          byName[ab + '|' + pkey(info.displayName)] = p;
        }
      }
    }
    for (const id in players){ players[id].xb = xb[id] || [0, 0]; players[id].sb = steals[id] || 0; }
    return {players, byName};
  }

  // A leg's current number from the player's box line (null: the stat isn't one we can read).
  function value(sport, stat, p){
    const g = k => num(p.s[k]);
    if (sport === 'nfl'){
      const m = {pass_yds: g('passing.passingYards'), pass_td: g('passing.passingTouchdowns'),
        pass_cmp: num(p.s['passing.completions/passingAttempts']), pass_att: second(p.s['passing.completions/passingAttempts']),
        rush_yds: g('rushing.rushingYards'), rec: g('receiving.receptions'), rec_yds: g('receiving.receivingYards'),
        rec_td: g('receiving.receivingTouchdowns'), rush_rec_yds: g('rushing.rushingYards') + g('receiving.receivingYards')};
      return m[stat] ?? null;
    }
    if (sport === 'nba'){
      const k = Object.keys(p.s), f = n => num(p.s[k.find(x => x.endsWith('.' + n))]);
      const pts = f('points'), reb = f('rebounds'), ast = f('assists');
      const m = {pts, reb, ast, tpm: num(p.s[k.find(x => x.includes('threePointFieldGoalsMade'))]), stl: f('steals'),
        blk: f('blocks'), to: f('turnovers'), pra: pts + reb + ast, pr: pts + reb, pa: pts + ast, ra: reb + ast};
      return m[stat] ?? null;
    }
    if (sport === 'nhl'){
      const k = Object.keys(p.s), f = n => num(p.s[k.find(x => x.endsWith('.' + n))]);
      const m = {g: f('goals'), a: f('assists'), pts: f('goals') + f('assists'), sog: f('shotsTotal')};
      return m[stat] ?? null;
    }
    if (sport === 'mlb'){
      const h = g('batting.hits'), hr = g('batting.homeRuns'), extra = Math.max(0, h - hr);
      const dbl = Math.min(p.xb[0], extra), tpl = Math.min(p.xb[1], Math.max(0, extra - dbl));
      const m = {h, hr, rbi: g('batting.RBIs'), r: g('batting.runs'), bb: g('batting.walks'), so: g('batting.strikeouts'),
        hrr: h + g('batting.runs') + g('batting.RBIs'), tb: h + dbl + 2 * tpl + 3 * hr, sb: p.sb,
        k: g('pitching.strikeouts'), outs: outs(p.s['pitching.fullInnings.partInnings']), ha: g('pitching.hits'),
        er: g('pitching.earnedRuns'), pbb: g('pitching.walks')};
      return m[stat] ?? null;
    }
    return null;
  }

  async function board(sport, day){
    const key = sport + '|' + day, b = boards[key];
    if (b && Date.now() - b.at < POLL_MS - 2000) return b.events;
    const d = await getJSON(`${API}${PATH[sport]}/scoreboard?dates=${day}`);
    boards[key] = {at: Date.now(), events: d.events || []};
    return boards[key].events;
  }

  async function box(sport, ev){
    const key = sport + '|' + ev.id, state = ((ev.status || {}).type || {}).state;
    if (state === 'pre') return null;
    if (boxes[key] && boxes[key].final) return boxes[key];
    const b = parseBox(sport, await getJSON(`${API}${PATH[sport]}/summary?event=${ev.id}`));
    b.final = state === 'post';
    return boxes[key] = b;
  }

  // Where a leg stands right now: {state: pre|live|post|na, v, status, verdict: hit|miss|push|alive|dnp|null}.
  async function legLive(l){
    if (!PATH[l.sport] || !l.start) return {state: 'na'};
    const events = await board(l.sport, etDate(l.start));
    const mine = events.filter(e => ((e.competitions || [{}])[0].competitors || []).some(c => team(l.sport, (c.team || {}).abbreviation) === l.team));
    const ev = mine.sort((a, b) => Math.abs(Date.parse(a.date) - Date.parse(l.start)) - Math.abs(Date.parse(b.date) - Date.parse(l.start)))[0];
    if (!ev) return {state: 'na'};
    const st = (ev.status || {}).type || {}, status = st.shortDetail || st.detail || '';
    if (st.state === 'pre') return {state: 'pre', status};
    if (st.state === 'post' && !st.completed) return {state: 'post', status, verdict: null};   // postponed / canceled
    const b = await box(l.sport, ev);
    const p = (l.sport !== 'nfl' && b.players[String(l.pid)]) || b.byName[l.team + '|' + pkey(l.player)];
    const final = st.state === 'post';
    if (!p || p.dnp){
      // An NFL player with no catch or carry isn't in the box at all, so missing there means 0 so far.
      if (l.sport === 'nfl' && !(p && p.dnp)) return judge(l, 0, final, status);
      return {state: final ? 'post' : 'live', status, v: null, verdict: final ? 'dnp' : 'alive'};
    }
    const v = value(l.sport, l.stat, p);
    return v == null ? {state: final ? 'post' : 'live', status, v: null, verdict: null} : judge(l, v, final, status);
  }

  function judge(l, v, final, status){
    const line = +l.line, over = l.side !== 'under';
    let verdict = 'alive';
    if (over && v > line) verdict = 'hit';             // an over is cashed the moment it clears
    else if (!over && v > line) verdict = 'miss';      // an under is dead the moment it goes past
    else if (final) verdict = v === line ? 'push' : over ? 'miss' : 'hit';
    return {state: final ? 'post' : 'live', status, v, verdict};
  }

  const OFFICIAL = {hit: 'hit', miss: 'miss', push: 'push', dnp: 'dnp', void: 'dnp'};
  const TAG = {hit: '<b class="up">✅ In</b>', miss: '<b class="down">❌ Out</b>', push: 'Push', dnp: 'DNP'};

  function legHTML(l, r){
    if (r.state === 'na') return '';
    if (r.state === 'pre') return `<span class="pl-lv"><span class="pl-lvst">${esc(r.status)}</span></span>`;
    const line = +l.line, v = r.v;
    const pct = v == null ? 0 : Math.max(0, Math.min(100, v / (line || 1) * 100));
    let note = '';
    if (r.verdict === 'alive' && v != null) note = l.side !== 'under' ? `needs ${+(Math.floor(line) + 1 - v).toFixed(1)} more` : `${+(line - v).toFixed(1)} to spare`;
    return `<span class="pl-lv${r.state === 'live' ? ' on' : ''}"><span class="pl-lvn"><b>${v == null ? '–' : esc(v)}</b> / ${esc(l.line)}</span>` +
      `<span class="pl-lvbar"><i style="width:${pct}%" class="${r.verdict === 'miss' ? 'bad' : r.verdict === 'hit' ? 'ok' : ''}"></i></span>` +
      `<span class="pl-lvst">${r.state === 'live' ? '<span class="pl-dot"></span>' : ''}${esc(r.status)}${note ? ' · ' + note : ''}${TAG[r.verdict] ? ' · ' + TAG[r.verdict] : ''}</span></span>`;
  }

  function cardHTML(t, rs){
    const v = t.legs.map((l, j) => OFFICIAL[l.res] || rs[j].verdict);
    const live = rs.filter(r => r.state === 'live').length, inn = v.filter(x => x === 'hit').length;
    const counted = t.legs.filter((l, j) => v[j] !== 'push' && v[j] !== 'dnp').length;
    if (t.res) return '';
    if (v.includes('miss')) return '<span class="pl-alive down">❌ Busted</span>';
    if (counted && v.every(x => x === 'hit' || x === 'push' || x === 'dnp')) return '<span class="pl-alive up">✅ Cashed · official grade after the next update</span>';
    if (rs.every(r => r.state === 'pre' || r.state === 'na')) return '';
    return `<span class="pl-alive up">${live ? '<span class="pl-dot"></span>' : ''}Alive · ${inn} of ${counted} in${live ? ` · ${live} live` : ''}</span>`;
  }

  async function tick(){
    if (!parlays.length) return stop();
    let busy = false;
    for (const [i, t] of parlays.entries()){
      const rs = await Promise.all(t.legs.map(l => legLive(l).catch(() => ({state: 'na'}))));
      const card = document.querySelector(`.pl-card[data-pl="${i}"]`);
      if (!card) continue;
      rs.forEach((r, j) => {
        const el = card.querySelector(`[data-leg="${j}"] .pl-live`);
        if (el) el.innerHTML = t.legs[j].res ? '' : legHTML(t.legs[j], r);
        if (!t.legs[j].res && r.state !== 'post' && r.state !== 'na') busy = true;
      });
      const hd = card.querySelector('.pl-livehd');
      if (hd) hd.innerHTML = cardHTML(t, rs);
    }
    updated = new Date();
    const note = document.getElementById('plLive');
    if (note) note.textContent = busy ? `Live from ESPN box scores · refreshed ${updated.toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit', second: '2-digit'})} · every 30 seconds`
      : updated && parlays.some(t => t.legs.some(l => !l.res)) ? 'All of today’s games are final: official grades come with the next update.' : '';
    if (!busy) stop();
  }

  function stop(){ clearInterval(timer); timer = null; }

  window.psaParlayLive = {
    track(list){
      parlays = (list || []).filter(t => t && t.legs && t.legs.length);
      stop();
      if (!parlays.length) return;
      tick();
      timer = setInterval(() => { if (document.visibilityState === 'visible') tick(); }, POLL_MS);
    },
    _value: value, _judge: judge, _parseBox: parseBox
  };
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && timer) tick(); });
})();
