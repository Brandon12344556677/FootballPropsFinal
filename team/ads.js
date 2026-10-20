// Meta ads panel on the team dashboard (team/index.html): draws feed (1080x1080) and story (1080x1920)
// ads on a canvas from ../today.json, so every number is the live record, and saves them as PNGs.
// Copy rules for Meta: no "bet", "lock" or exchange names, an 18+ line on every ad (see the panel's notes).
// Each kind also has a script(): the three lines the owner films for the 15s video ad (team/ads_video.js).
(function(){
  'use strict';
  const $ = id => document.getElementById(id);
  const C = {bg:'#0a1628', surface:'#0f2038', line:'#22354f', fg:'#ffffff', soft:'#dfe6ef', muted:'#9fb0c6',
    green:'#22d07f', ink:'#06210b', red:'#eb6f7d', gold:'#e8b54a', grey:'rgba(159,176,198,.35)'};
  const DISP = 'Archivo, Inter, sans-serif', BODY = 'Inter, sans-serif', LBL = '"Barlow Condensed", Inter, sans-serif';
  const NAME = {nfl:'NFL', nba:'NBA', nhl:'NHL', mlb:'MLB'};
  const pc = v => Math.round(v*100);
  const fmt = n => (n||0).toLocaleString('en-US');
  const side = s => s === 'over' ? 'Over' : 'Under';
  const an = n => (n === 11 || n === 18 || String(n)[0] === '8') ? 'an' : 'a';   // "an 88%", "a 72%"
  const shortDay = iso => new Date(iso).toLocaleDateString('en-US', {weekday:'long', timeZone:'America/New_York'});
  const dateLbl = iso => new Date(iso).toLocaleDateString('en-US', {month:'short', day:'numeric', timeZone:'America/New_York'});
  let T = null, blob = null, fileName = '';

  // ---------- drawing helpers ----------
  function setFont(g, w, px, fam, ls){ g.font = `${w} ${px}px ${fam}`; if ('letterSpacing' in g) g.letterSpacing = (ls||0) + 'px'; }
  function txt(g, s, x, y, o={}){
    setFont(g, o.w||600, o.px||32, o.fam||BODY, o.ls); g.fillStyle = o.color||C.fg; g.textAlign = o.align||'left';
    g.fillText(s, x, y); const m = g.measureText(s).width; g.textAlign = 'left'; if ('letterSpacing' in g) g.letterSpacing = '0px'; return m;
  }
  function rich(g, segs, x, y, px){   // one headline line in colored pieces: [[text, color], ...]
    for (const [s, c] of segs) x += txt(g, s, x, y, {w:800, px, fam:DISP, color:c, ls:-px*0.03});
  }
  function wrap(g, s, maxW){
    const out = []; let line = '';
    for (const w of s.split(' ')){ const t = line ? line + ' ' + w : w; if (g.measureText(t).width > maxW && line){ out.push(line); line = w; } else line = t; }
    if (line) out.push(line); return out;
  }
  function backdrop(g, W, H){
    g.fillStyle = C.bg; g.fillRect(0, 0, W, H);
    g.strokeStyle = 'rgba(34,208,127,.045)'; g.lineWidth = 2;
    for (let x = 0; x <= W; x += 96){ g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
    for (let y = 0; y <= H; y += 96){ g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
    let r = g.createRadialGradient(90, -130, 0, 90, -130, 1200); r.addColorStop(0, 'rgba(34,208,127,.18)'); r.addColorStop(1, 'rgba(34,208,127,0)');
    g.fillStyle = r; g.fillRect(0, 0, W, H);
    r = g.createRadialGradient(W*1.05, H*1.05, 0, W*1.05, H*1.05, 900); r.addColorStop(0, 'rgba(34,208,127,.08)'); r.addColorStop(1, 'rgba(34,208,127,0)');
    g.fillStyle = r; g.fillRect(0, 0, W, H);
  }
  function brand(g, x, y){
    g.save(); g.translate(x, y);
    g.fillStyle = C.surface; g.strokeStyle = 'rgba(34,208,127,.35)'; g.lineWidth = 2; g.beginPath(); g.roundRect(0, 0, 60, 60, 14); g.fill(); g.stroke();
    g.scale(60/64, 60/64); g.fillStyle = C.green; g.beginPath(); g.moveTo(32, 6); g.quadraticCurveTo(32, 32, 54, 32); g.quadraticCurveTo(32, 32, 32, 58);
    g.quadraticCurveTo(32, 32, 10, 32); g.quadraticCurveTo(32, 32, 32, 6); g.fill(); g.restore();
    g.textBaseline = 'middle';
    let cx = x + 76; cx += txt(g, 'Prop ', cx, y+31, {w:800, px:36, fam:DISP}); cx += txt(g, 'Streak ', cx, y+31, {w:'italic 600', px:36, fam:DISP, color:C.green});
    txt(g, 'Lab', cx, y+31, {w:800, px:36, fam:DISP}); g.textBaseline = 'alphabetic';
  }
  function pill(g, s, right, cy, gold){
    s = s.toUpperCase(); setFont(g, 700, 26, LBL, 3.5); const w = g.measureText(s).width + 68, x = right - w;
    g.fillStyle = gold ? 'rgba(232,181,74,.08)' : 'rgba(34,208,127,.09)'; g.strokeStyle = gold ? 'rgba(232,181,74,.4)' : 'rgba(34,208,127,.35)'; g.lineWidth = 2;
    g.beginPath(); g.roundRect(x, cy-27, w, 54, 27); g.fill(); g.stroke();
    g.fillStyle = gold ? C.gold : C.green; g.beginPath(); g.arc(x+28, cy, 6, 0, Math.PI*2); g.fill();
    g.textBaseline = 'middle'; txt(g, s, x+46, cy+1, {w:700, px:26, fam:LBL, color:gold ? C.gold : C.green, ls:3.5}); g.textBaseline = 'alphabetic';
  }
  function card(g, x, y, w, h, accent){
    const gr = g.createLinearGradient(0, y, 0, y+h); gr.addColorStop(0, 'rgba(20,39,67,.92)'); gr.addColorStop(1, 'rgba(12,26,48,.95)');
    g.fillStyle = gr; g.strokeStyle = accent ? 'rgba(34,208,127,.55)' : C.line; g.lineWidth = 2; g.beginPath(); g.roundRect(x, y, w, h, 32); g.fill(); g.stroke();
  }
  function label(g, s, x, y, color, align){ return txt(g, s.toUpperCase(), x, y, {w:700, px:24, fam:LBL, color:color||C.muted, ls:3.4, align}); }
  function lede(g, s, x, y, maxW){
    setFont(g, 500, 34, BODY); const lines = wrap(g, s, maxW);
    lines.forEach((l, i) => txt(g, l, x, y + i*46, {w:500, px:34, color:C.soft})); return y + (lines.length-1)*46;
  }
  function footer(g, W, bottom, cta, fine){
    setFont(g, 800, 34, BODY); const bw = g.measureText(cta + '  →').width + 72, bh = 84, bx = W - 80 - bw, by = bottom - bh;
    g.save(); g.shadowColor = 'rgba(34,208,127,.25)'; g.shadowBlur = 40; g.shadowOffsetY = 14; g.fillStyle = C.green;
    g.beginPath(); g.roundRect(bx, by, bw, bh, 42); g.fill(); g.restore();
    g.textBaseline = 'middle'; txt(g, cta + '  →', bx+36, by+bh/2+1, {w:800, px:34, color:C.ink}); g.textBaseline = 'alphabetic';
    setFont(g, 500, 20, BODY); const lines = wrap(g, fine, bx - 80 - 28);
    lines.forEach((l, i) => txt(g, l, 80, bottom - 6 - (lines.length-1-i)*27, {w:500, px:20, color:'#7f91a9'}));
    txt(g, 'PROPSTREAKLAB.COM', 80, bottom - 6 - (lines.length-1)*27 - 44, {w:700, px:28, fam:LBL, color:C.muted, ls:2.8});
  }

  // ---------- the four live ads: each draws its body from y and returns where it ended ----------
  const CTA_LINE = "It's free, no account needed. Tap the link.";
  const ADS = {
    proof: {
      title: 'Calibration (proof)',
      ok: () => (T.calib||[]).length >= 3,
      pill: () => [fmt(T.calib.reduce((a, b) => a + b.n, 0)) + ' graded picks', true],
      body(g, W, y){
        const cal = T.calib, b = cal.find(r => r.lo === 70) || cal[Math.floor(cal.length/2)];
        rich(g, [['When we say ', C.fg], [pc(b.said)+'%', C.green], [',', C.fg]], 80, y+84, 92);
        rich(g, [['it hits ', C.fg], [pc(b.hit)+'%', C.green], ['.', C.fg]], 80, y+176, 92);
        y = lede(g, 'Every pick recorded before the game, graded after.', 80, y+252, W-160);
        const cy = y + 40, ch = 70 + cal.length*53 + 54; card(g, 80, cy, W-160, ch);
        const tx = 80+40+200+24, tw = (W-80-40-150-24) - tx;
        label(g, 'Model said', 120, cy+52); label(g, 'Actually hit', tx, cy+52);
        cal.forEach((r, i) => {
          const ry = cy + 70 + i*53 + 26, hl = r === b;
          txt(g, `${r.lo}–${r.hi}%`, 120, ry+12, {w:700, px:34, fam:LBL, color:hl ? C.green : C.soft, ls:1.3});
          g.fillStyle = 'rgba(255,255,255,.06)'; g.beginPath(); g.roundRect(tx, ry-15, tw, 30, 15); g.fill();
          g.fillStyle = 'rgba(232,181,74,.14)'; g.strokeStyle = 'rgba(232,181,74,.55)'; g.setLineDash([6, 5]); g.lineWidth = 2;
          g.beginPath(); g.roundRect(tx + tw*r.lo/100, ry-23, tw*(r.hi-r.lo)/100, 46, 10); g.fill(); g.stroke(); g.setLineDash([]);
          const gr = g.createLinearGradient(tx, 0, tx + tw*r.hit, 0); gr.addColorStop(0, '#14824f'); gr.addColorStop(1, C.green);
          g.fillStyle = gr; g.beginPath(); g.roundRect(tx, ry-15, tw*r.hit, 30, 15); g.fill();
          txt(g, pc(r.hit)+'%', W-120, ry+15, {w:800, px:42, color:hl ? C.green : C.fg, align:'right', ls:-0.8});
        });
        const ly = cy + ch - 30; g.fillStyle = C.green; g.beginPath(); g.roundRect(120, ly-14, 34, 16, 8); g.fill();
        const lw = txt(g, 'Actual hit rate', 166, ly, {w:500, px:22, color:C.muted});
        g.fillStyle = 'rgba(232,181,74,.14)'; g.strokeStyle = 'rgba(232,181,74,.55)'; g.setLineDash([5, 4]); g.beginPath(); g.roundRect(166+lw+30, ly-14, 34, 16, 5); g.fill(); g.stroke(); g.setLineDash([]);
        txt(g, 'What the model promised', 166+lw+76, ly, {w:500, px:22, color:C.muted});
        return cy + ch;
      },
      cta: 'See the full record',
      fine: () => `Live NFL, NBA, NHL & MLB picks, graded through ${dateLbl(T.gen)}. Past results don't guarantee future ones. 18+.`,
      script(){
        const b = T.calib.find(r => r.lo === 70) || T.calib[0], n = T.calib.reduce((a, r) => a + r.n, 0);
        return {hook: `When our model says ${pc(b.said)}%, it hits ${pc(b.hit)}%.`,
          middle: `We've graded ${fmt(n)} player props. Every one is recorded before the game and graded after, misses included.`, cta: CTA_LINE};
      },
      copy(){
        const b = T.calib.find(r => r.lo === 70) || T.calib[0], n = T.calib.reduce((a, r) => a + r.n, 0);
        return {primary: `When our model says ${pc(b.said)}%, it hits ${pc(b.hit)}%. ${fmt(n)} player props, every one recorded before the game and graded after, misses included. Free research for NFL, NBA, NHL and MLB.`,
          headline: 'Player prop research, graded in public', description: 'Free · No account needed'};
      }
    },
    record: {
      title: 'Season record (one sport)',
      pickLabel: 'Sport',
      options: () => Object.keys(NAME).filter(s => T.record && T.record[s] && T.record[s].T && T.record[s].T.n >= 30)
        .map(s => ({v:s, t:`${NAME[s]}: Top 25 ${T.record[s].T.hit}/${T.record[s].T.n}`})),
      pill: s => [NAME[s] + ' · graded in public'],
      body(g, W, y, s){
        const r = T.record[s], t = r.T, v = r.V || {};
        rich(g, [[pc(t.hit/t.n)+'%', C.green], [' of our top', C.fg]], 80, y+84, 92);
        rich(g, [[NAME[s] + ' picks hit.', C.fg]], 80, y+176, 92);
        y = lede(g, `${fmt(t.hit)} of ${fmt(t.n)} "Top 25 Surest" picks this season. Every one recorded before the game.`, 80, y+252, W-160);
        const cy = y + 44, cw = (W-160-26)/2, ch = 300;
        const box = (x, lbl, rec, accent) => {
          card(g, x, cy, cw, ch, accent); label(g, lbl, x+36, cy+58, accent ? C.green : C.muted);
          txt(g, `${fmt(rec.hit)}/${fmt(rec.n)}`, x+32, cy+168, {w:800, px:96, fam:DISP, color:accent ? C.green : C.soft, ls:-4});
          txt(g, `${pc(rec.hit/rec.n)}% hit`, x+36, cy+222, {w:600, px:30, color:C.soft});
          if (rec.units != null && rec.priced) txt(g, `${rec.units >= 0 ? '+' : '−'}${Math.abs(rec.units).toFixed(1)} units at market prices`, x+36, cy+262, {w:500, px:24, color:C.muted});
        };
        box(80, 'Top 25 Surest', t, true);
        if (v.n) box(80+cw+26, 'Value spots', v, false);
        return cy + ch;
      },
      cta: 'See every pick',
      fine: () => `Live picks this season, through ${dateLbl(T.gen)}. Units: return on 1 unit per priced pick. Past results don't guarantee future ones. 18+.`,
      script(s){
        const t = T.record[s].T;
        return {hook: `${pc(t.hit/t.n)}% of our top ${NAME[s]} player props have hit this season.`,
          middle: `That's ${fmt(t.hit)} of ${fmt(t.n)}, each one posted before the game and graded after, so you can check every pick.`, cta: CTA_LINE};
      },
      copy(s){
        const t = T.record[s].T;
        return {primary: `${pc(t.hit/t.n)}% of our top ${NAME[s]} player props have hit this season (${fmt(t.hit)} of ${fmt(t.n)}). Every pick is recorded before the game and graded after. See the whole record free.`,
          headline: `${NAME[s]} props, graded in public`, description: 'Free · No account needed'};
      }
    },
    gap: {
      title: "Today's biggest gap (model vs. market)",
      pickLabel: 'Prop',
      options: () => (T.picks||[]).filter(p => p.kind === 'value' && p.price && Date.parse(p.start) > Date.now())
        .map((p, i) => ({v:String(i), p, t:`${NAME[p.sport]} · ${p.player} ${side(p.side)} ${p.line} ${p.statText}: ${pc(p.prob)}% vs ${pc(p.price)}%`})),
      pill: p => [`${NAME[p.sport]} · ${shortDay(p.start)}`],
      body(g, W, y, p){
        rich(g, [['The model and the', C.fg]], 80, y+84, 92);
        rich(g, [['market ', C.fg], ['disagree', C.green], ['.', C.fg]], 80, y+176, 92);
        const cy = y + 214, l10 = (p.l10||[]).filter(v => v != null), ch = l10.length ? 490 : 300; card(g, 80, cy, W-160, ch);
        txt(g, p.player, 120, cy+80, {w:800, px:56, fam:DISP, ls:-1.4});
        let x = 120; x += txt(g, `${p.statText} · `, x, cy+128, {w:500, px:30, color:C.soft});
        x += txt(g, `${side(p.side)} ${p.line}`, x, cy+128, {w:700, px:30, color:C.green}); txt(g, ` · vs. ${p.opp}`, x, cy+128, {w:500, px:30, color:C.soft});
        txt(g, pc(p.prob)+'%', 116, cy+250, {w:800, px:112, fam:DISP, color:C.green, ls:-5}); label(g, 'Model chance', 120, cy+292, C.green);
        txt(g, pc(p.price)+'%', W-120, cy+250, {w:800, px:112, fam:DISP, color:C.soft, align:'right', ls:-5}); label(g, 'Market price', W-120, cy+292, C.muted, 'right');
        const gx = W/2 - 48; g.fillStyle = C.green; g.beginPath(); g.roundRect(gx, cy+170, 96, 82, 16); g.fill();
        txt(g, '+' + (pc(p.prob) - pc(p.price)), W/2, cy+215, {w:800, px:34, fam:LBL, color:C.ink, align:'center'});
        txt(g, 'PTS', W/2, cy+240, {w:800, px:20, fam:LBL, color:C.ink, align:'center', ls:2.8});
        if (l10.length){
          const bx = 120, bw = W-240, by = cy+430, bh = 100, max = Math.max(...l10, p.line*1.15) || 1, gap = 14, w = (bw - gap*(l10.length-1))/l10.length;
          let hits = 0;
          l10.forEach((v, i) => {   // l10 is oldest first (build_today.last10)
            const hit = p.side === 'over' ? v > p.line : v < p.line; hits += hit;
            const h = Math.max(6, bh*v/max); g.fillStyle = hit ? C.green : C.grey; g.beginPath(); g.roundRect(bx + i*(w+gap), by-h, w, h, [10, 10, 4, 4]); g.fill();
          });
          const lyy = by - bh*p.line/max; g.strokeStyle = C.gold; g.lineWidth = 3; g.setLineDash([9, 7]); g.beginPath(); g.moveTo(bx-8, lyy); g.lineTo(bx+bw+8, lyy); g.stroke(); g.setLineDash([]);
          label(g, 'Line ' + p.line, bx+bw, lyy-12, C.gold, 'right');
          label(g, `Last ${l10.length} games · ${hits} ${p.side}`, 120, cy+ch-24);
        }
        return cy + ch;
      },
      cta: "See today's board",
      fine: () => `Model chance, not a guarantee. Market price as of ${new Date(T.gen).toLocaleTimeString('en-US', {hour:'numeric', minute:'2-digit', timeZone:'America/New_York'})} ET. 18+.`,
      script(p){
        return {hook: `Our model and the market disagree on ${p.player} today.`,
          middle: `The model gives ${p.side} ${p.line} ${p.statText.toLowerCase()} ${an(pc(p.prob))} ${pc(p.prob)}% chance. The market says ${pc(p.price)}%. See the math and the last 10 games.`, cta: CTA_LINE};
      },
      copy(p){
        return {primary: `Our model gives ${p.player} ${an(pc(p.prob))} ${pc(p.prob)}% chance of going ${p.side} ${p.line} ${p.statText.toLowerCase()}. The market says ${pc(p.price)}%. See the math, the matchup and the last 10 games, free.`,
          headline: 'See where the model disagrees', description: 'Free player prop research'};
      }
    },
    streak: {
      title: 'Hit streak',
      pickLabel: 'Streak',
      options: () => (T.streaks||[]).filter(s => Date.parse(s.start) > Date.now() && s.streak >= 5)
        .map((s, i) => ({v:String(i), p:s, t:`${NAME[s.sport]} · ${s.player} ${side(s.side)} ${s.line} ${s.statText}: ${s.streak} straight`})),
      pill: s => [`${NAME[s.sport]} · hit streak`],
      body(g, W, y, s){
        rich(g, [[s.streak + ' straight', C.green]], 80, y+84, 92);
        rich(g, [['games ' + s.side + '.', C.fg]], 80, y+176, 92);
        y = lede(g, `${s.player} has gone ${s.side} ${s.line} ${s.statText.toLowerCase()} in ${s.streak} straight games. Will it be ${s.streak+1}?`, 80, y+252, W-160);
        const cy = y + 44, ch = 360; card(g, 80, cy, W-160, ch, true);
        txt(g, s.player, 120, cy+80, {w:800, px:56, fam:DISP, ls:-1.4});
        txt(g, `${s.statText} · ${side(s.side)} ${s.line} · vs. ${s.opp}`, 120, cy+128, {w:500, px:30, color:C.soft});
        const n = Math.min(s.streak, 12), sw = 52, sg = 12;
        for (let i = 0; i < n; i++){ g.fillStyle = C.green; g.beginPath(); g.roundRect(120 + i*(sw+sg), cy+160, sw, sw, 12); g.fill(); }
        txt(g, pc(s.prob)+'%', 116, cy+320, {w:800, px:96, fam:DISP, color:C.green, ls:-4});
        label(g, 'Model chance it continues', 330, cy+300, C.green);
        if (s.price) txt(g, `Market price ${pc(s.price)}%`, 330, cy+334, {w:500, px:26, color:C.muted});
        return cy + ch;
      },
      cta: 'See the streak board',
      fine: () => 'Model chance, not a guarantee. Streaks end. 18+.',
      script(s){
        return {hook: `${s.player} has gone ${s.side} ${s.line} ${s.statText.toLowerCase()} in ${s.streak} straight games.`,
          middle: `Will it be ${s.streak+1}? Our model gives it ${an(pc(s.prob))} ${pc(s.prob)}% chance to keep going, and every call is graded in public.`, cta: CTA_LINE};
      },
      copy(s){
        return {primary: `${s.player}: ${s.streak} straight games ${s.side} ${s.line} ${s.statText.toLowerCase()}. Our model gives it ${an(pc(s.prob))} ${pc(s.prob)}% chance to keep going. Free player prop research for NFL, NBA, NHL and MLB.`,
          headline: 'Will the streak keep going?', description: 'Free player prop research'};
      }
    }
  };

  // ---------- panel ----------
  function current(){
    const k = $('adKind').value, ad = ADS[k], opts = ad.options ? ad.options() : null;
    const o = opts ? opts.find(x => x.v === $('adPick').value) || opts[0] : null;
    return {k, ad, arg: o ? (o.p || o.v) : null, empty: opts ? !opts.length : !ad.ok()};
  }
  function fillPicks(){
    const ad = ADS[$('adKind').value], sel = $('adPick'), wrapEl = $('adPickWrap');
    sel.textContent = '';
    if (!ad.options){ wrapEl.hidden = true; return; }
    wrapEl.hidden = false; $('adPickLbl').firstChild.textContent = ad.pickLabel + ' ';
    const opts = ad.options();
    for (const o of opts){ const op = document.createElement('option'); op.value = o.v; op.textContent = o.t; sel.appendChild(op); }
    if (!opts.length){ const op = document.createElement('option'); op.textContent = 'Nothing available right now'; sel.appendChild(op); }
  }
  async function fonts(){
    try { await Promise.all(['800 92px Archivo', 'italic 600 36px Archivo', '600 32px Inter', '800 64px Inter', '700 26px "Barlow Condensed"'].map(f => document.fonts.load(f))); } catch(e){}
  }
  function paint(g, W, H, k, arg, story, cta){
    const ad = ADS[k], top = story ? 150 : 72, bottom = story ? H - 220 : H - 64;   // story: keep clear of Instagram's top bar and reply box
    let y0 = top + 60 + (story ? 4 : 40);
    if (story){   // center the body between the header and the footer
      const m = document.createElement('canvas').getContext('2d'); const end = ad.body(m, W, 0, arg);
      y0 = Math.max(y0 + 40, Math.round((top + 60 + bottom - 130) / 2 - end / 2));
    }
    backdrop(g, W, H); brand(g, 80, top);
    const [ptxt, gold] = ad.pill(arg); pill(g, ptxt, W-80, top+30, gold);
    ad.body(g, W, y0, arg);
    footer(g, W, bottom, cta || ad.cta, ad.fine(arg));
  }
  function endCard(g, W, H, k, arg, cta){   // the video's last two seconds (1080x1920)
    const ad = ADS[k], top = 150;
    backdrop(g, W, H); brand(g, 80, top);
    const y = Math.round(H/2) - 260;
    rich(g, [['Player prop', C.fg]], 80, y, 92);
    rich(g, [['research, ', C.fg]], 80, y+92, 92);
    rich(g, [['graded in ', C.fg], ['public.', C.green]], 80, y+184, 92);
    lede(g, 'NFL, NBA, NHL & MLB. Every pick recorded before the game and graded after.', 80, y+262, W-160);
    setFont(g, 700, 26, LBL, 3.5); pill(g, 'Free · No account needed', 80 + g.measureText('FREE · NO ACCOUNT NEEDED').width + 68, y+400);   // left-aligned
    footer(g, W, H - 220, cta || ad.cta, ad.fine(arg));
  }
  function copyFor(k, ad, arg, video){
    const cp = ad.copy(arg), camp = `facebook-meta-${video ? 'video-' : ''}${k}-${dateLbl(new Date().toISOString()).toLowerCase().replace(/\W+/g, '-')}`;
    cp.link = `https://propstreaklab.com/?utm_source=facebook&utm_campaign=${camp}`;
    return cp;
  }
  function showFmt(){   // Video swaps the image preview for the video maker (team/ads_video.js)
    const vid = $('adFmt').value === 'video';
    $('adMake').hidden = vid;
    if ($('adVideo')) $('adVideo').hidden = !vid;
    if (vid){ $('adPrev').hidden = true; $('adSave').hidden = true; }
    else if (blob){ $('adPrev').hidden = false; $('adSave').hidden = false; }
    return vid;
  }
  async function draw(){
    const {k, ad, arg, empty} = current(), vid = showFmt();
    if (empty){
      $('adMsg').textContent = 'Nothing to make this ad from right now. Try another kind, or check back after the next update.';
      if ($('adVideo')) $('adVideo').hidden = true; return;
    }
    await fonts();
    if (vid){
      $('adMsg').textContent = '';
      renderCopy(copyFor(k, ad, arg, true));
      if (window.psaAds.onVideo) window.psaAds.onVideo({k, ad, arg});
      return;
    }
    const story = $('adFmt').value === 'story', W = 1080, H = story ? 1920 : 1080;
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    paint(c.getContext('2d'), W, H, k, arg, story);
    blob = await new Promise(res => c.toBlob(res, 'image/png'));
    if ($('adFmt').value === 'video') return;   // switched to Video while this was drawing
    const day = new Date().toLocaleDateString('en-CA', {timeZone:'America/New_York'});
    fileName = `prop-streak-lab-meta-${k}-${story ? 'story' : 'feed'}-${day}.png`;
    $('adPrev').src = URL.createObjectURL(blob); $('adPrev').hidden = false; $('adPrev').classList.toggle('story', story);
    $('adSave').hidden = false; $('adMsg').textContent = '';
    renderCopy(copyFor(k, ad, arg, false));
  }
  function renderCopy(cp){
    const box = $('adCopy'); box.textContent = ''; box.hidden = false;
    [['Primary text', cp.primary], ['Headline', cp.headline], ['Description', cp.description], ['Website URL (tracked)', cp.link]].forEach(([lbl, val]) => {
      const row = document.createElement('div'); row.className = 'adc';
      row.innerHTML = '<span class="label"></span><div class="out"><input type="text" readonly><button class="btn ghost-btn" type="button">Copy</button></div>';
      row.querySelector('.label').textContent = lbl + (lbl === 'Primary text' ? ` · ${val.length} chars` : '');
      const inp = row.querySelector('input'); inp.value = val;
      row.querySelector('button').onclick = async e => {
        try { await navigator.clipboard.writeText(val); e.target.textContent = 'Copied'; } catch(err){ inp.select(); e.target.textContent = 'Press Ctrl+C'; }
        setTimeout(() => e.target.textContent = 'Copy', 2000);
      };
      box.appendChild(row);
    });
  }
  async function save(){
    if (!blob) return;
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = fileName; document.body.appendChild(a); a.click(); a.remove();
    $('adMsg').textContent = 'Downloaded. On an iPhone, if it opened in a new tab, press and hold the image to save it.';
  }
  async function init(){
    if (!$('adKind')) return;
    $('adMake').disabled = true; $('adMsg').textContent = 'Loading today\'s data…';
    T = await fetch('../today.json?t=' + Date.now(), {cache:'no-store'}).then(r => r.ok ? r.json() : null).catch(() => null);
    if (!T){ $('adMsg').textContent = 'Could not load today.json. Check your connection and reload.'; return; }
    $('adMake').disabled = false; $('adMsg').textContent = '';
    fillPicks();
  }
  // team/render.html (the daily TikTok drafts, tiktok_post.py) draws with the same pieces, without the panel
  window.psaAds = {ADS, paint, endCard, fonts, current, data: () => T, setData: d => { T = d; },
    draw: {C, DISP, BODY, LBL, NAME, pc, fmt, side, an, dateLbl, txt, rich, setFont, wrap, backdrop, brand, pill, card, label, lede, footer}};
  if ($('adKind')){
    $('adKind').addEventListener('change', () => { fillPicks(); if (T) draw(); });
    $('adPick').addEventListener('change', () => { if (T) draw(); });
    $('adFmt').addEventListener('change', () => { if (showFmt() || blob){ if (T) draw(); } });
    $('adMake').addEventListener('click', draw);
    $('adSave').addEventListener('click', save);
    init();
  }
})();
