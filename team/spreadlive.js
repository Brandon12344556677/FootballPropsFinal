/* Live scores for today's game-spread picks (dashboard's Spreads tab). spreads.enc only changes every
   update pass (~10 minutes) and a pick is graded only once spreads.py sees the final, so this reads
   ESPN's public scoreboards straight from the browser (they allow it) every 30 seconds while the tab is
   open and a game is still to finish: the score, the game clock, and whether the pick is covering
   right now (its team's margin plus the line above 0, as spreads.py grades it). Display only: the
   record is still spreads.py's grading. Picks carry ESPN's event id (gid) and whether the pick's team
   is at home, so no name matching is needed.
   Index: window.psaSpreadLive.track(picks, {root, note}) after the table renders: root is the id of the
   tbody (live cells are [data-sd="i"]), note the id of its status line. */
(function(){
  const POLL_MS = 30000;
  const PATH = {nfl: 'football/nfl', nba: 'basketball/nba', nhl: 'hockey/nhl', mlb: 'baseball/mlb'};
  const API = 'https://site.web.api.espn.com/apis/site/v2/sports/';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const etDate = s => new Date(s).toLocaleDateString('en-CA', {timeZone: 'America/New_York'}).replace(/-/g, '');
  const G = {picks: [], root: 'sdToday', note: 'sdLive', timer: null};

  async function board(sport, day){
    const r = await fetch(`${API}${PATH[sport]}/scoreboard?dates=${day}&limit=500`, {cache: 'no-store'});
    if (!r.ok) throw new Error(r.status);
    return (await r.json()).events || [];
  }

  // One ESPN event -> {state, status, team, opp, ts, os} from the pick's side.
  function game(p, ev){
    const comp = (ev.competitions || [{}])[0], side = {};
    (comp.competitors || []).forEach(c => { side[c.homeAway] = c; });
    const st = (ev.status || {}).type || {}, mine = side[p.home ? 'home' : 'away'], them = side[p.home ? 'away' : 'home'];
    if (!mine || !them) return {state: 'na'};
    const sc = c => { const n = parseFloat(c.score); return isFinite(n) ? n : 0; };
    return {state: st.state === 'post' && !st.completed ? 'off' : st.state, status: st.shortDetail || st.detail || '', start: ev.date,
            team: (mine.team || {}).abbreviation || p.team, opp: (them.team || {}).abbreviation || '', ts: sc(mine), os: sc(them)};
  }

  // Covering now: the pick's margin plus its line above 0 (a tie on the number is neither).
  function cover(p, g){
    const m = g.ts - g.os + (+p.line);
    return m > 0 ? 'cover' : m < 0 ? 'behind' : 'even';
  }

  function cellHTML(p, g){
    if (!g || g.state === 'na'){
      const t = Date.parse(p.start);
      return isFinite(t) && t > Date.now() ? 'Starts ' + new Date(t).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'}) : '–';
    }
    if (g.state === 'pre'){
      const t = Date.parse(p.start || g.start);
      return `<span class="sd-lv">${isFinite(t) ? 'Starts ' + new Date(t).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'}) : esc(g.status)}</span>`;
    }
    if (g.state === 'off') return `<span class="sd-lv">${esc(g.status)}</span>`;
    const c = cover(p, g), by = Math.abs(g.ts - g.os + (+p.line));
    const tag = c === 'cover' ? `<b class="up">${g.state === 'post' ? '✅ Covered' : 'Covering'} by ${+by.toFixed(1)}</b>`
      : c === 'behind' ? `<b class="down">${g.state === 'post' ? '❌ Missed' : 'Behind'} by ${+by.toFixed(1)}</b>` : 'Right on the number';
    return `<span class="sd-lv${g.state === 'in' ? ' on' : ''}"><b>${esc(g.team)} ${g.ts}</b> – ${esc(g.opp)} ${g.os} · ` +
      `${g.state === 'in' ? '<span class="pl-dot"></span>' : ''}${esc(g.status)} · ${tag}</span>`;
  }

  async function tick(){
    const open = G.picks.map((p, i) => [p, i]).filter(([p]) => !p.res && PATH[p.sport] && p.gid);
    if (!open.length) return stop();
    const boards = {};
    for (const [p] of open){
      const k = p.sport + '|' + etDate(p.start || Date.now());
      if (!(k in boards)) boards[k] = board(p.sport, k.split('|')[1]).catch(() => []);
    }
    const root = document.getElementById(G.root) || document;
    let busy = false;
    for (const [p, i] of open){
      const ev = (await boards[p.sport + '|' + etDate(p.start || Date.now())]).find(e => String(e.id) === String(p.gid));
      const g = ev ? game(p, ev) : {state: 'na'};
      const el = root.querySelector(`[data-sd="${i}"]`);
      if (el) el.innerHTML = cellHTML(p, g);
      if (g.state === 'pre' || g.state === 'in') busy = true;
    }
    const note = document.getElementById(G.note);
    if (note) note.textContent = busy ? `Live scores from ESPN · refreshed ${new Date().toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit', second: '2-digit'})} · every 30 seconds`
      : 'All of today’s games are final: official grades come with the next update.';
    if (!busy) stop();
  }

  function stop(){ clearInterval(G.timer); G.timer = null; }

  window.psaSpreadLive = {
    track(picks, opts){
      G.root = (opts && opts.root) || G.root; G.note = (opts && opts.note) || G.note;
      G.picks = picks || [];
      stop();
      const note = document.getElementById(G.note);
      if (note) note.textContent = '';
      if (!G.picks.some(p => !p.res)) return;
      tick();
      G.timer = setInterval(() => { if (document.visibilityState === 'visible') tick(); }, POLL_MS);
    },
    _cover: cover, _game: game
  };
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && G.timer) tick(); });
})();
