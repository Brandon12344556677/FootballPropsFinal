/* Prop Streak Lab — shared "app" behavior for the sport boards and the home page:
   team colors, the live ticker (with countdowns), chance-ring animation, loading
   shimmer and the hover spotlight on pick cards. Pages call PS.teamVars(),
   PS.ticker(items) and PS.skeleton(n); everything else runs by itself. Pairs with
   app.css. No network, no third parties. */
window.PS = (function(){
  // [primary, secondary] per team, keyed by each dataset's own team codes.
  const TEAMS = {
    nfl:{ARI:['#97233F','#FFB612'],ATL:['#A71930','#000000'],BAL:['#241773','#9E7C0C'],BUF:['#00338D','#C60C30'],CAR:['#0085CA','#101820'],
      CHI:['#0B162A','#C83803'],CIN:['#FB4F14','#000000'],CLE:['#311D00','#FF3C00'],DAL:['#003594','#869397'],DEN:['#FB4F14','#002244'],
      DET:['#0076B6','#B0B7BC'],GB:['#203731','#FFB612'],HOU:['#03202F','#A71930'],IND:['#002C5F','#A2AAAD'],JAX:['#006778','#D7A22A'],
      KC:['#E31837','#FFB81C'],LA:['#003594','#FFA300'],LAC:['#0080C6','#FFC20E'],LV:['#000000','#A5ACAF'],MIA:['#008E97','#FC4C02'],
      MIN:['#4F2683','#FFC62F'],NE:['#002244','#C60C30'],NO:['#D3BC8D','#101820'],NYG:['#0B2265','#A71930'],NYJ:['#125740','#FFFFFF'],
      PHI:['#004C54','#A5ACAF'],PIT:['#101820','#FFB612'],SEA:['#002244','#69BE28'],SF:['#AA0000','#B3995D'],TB:['#D50A0A','#FF7900'],
      TEN:['#0C2340','#4B92DB'],WAS:['#5A1414','#FFB612']},
    nba:{ATL:['#E03A3E','#C1D32F'],BKN:['#000000','#FFFFFF'],BOS:['#007A33','#BA9653'],CHA:['#1D1160','#00788C'],CHI:['#CE1141','#000000'],
      CLE:['#860038','#FDBB30'],DAL:['#00538C','#B8C4CA'],DEN:['#0E2240','#FEC524'],DET:['#C8102E','#1D42BA'],GS:['#1D428A','#FFC72C'],
      HOU:['#CE1141','#C4CED4'],IND:['#002D62','#FDBB30'],LAC:['#C8102E','#1D428A'],LAL:['#552583','#FDB927'],MEM:['#5D76A9','#12173F'],
      MIA:['#98002E','#F9A01B'],MIL:['#00471B','#EEE1C6'],MIN:['#0C2340','#78BE20'],NO:['#0C2340','#C8102E'],NY:['#006BB6','#F58426'],
      OKC:['#007AC1','#EF3B24'],ORL:['#0077C0','#C4CED4'],PHI:['#006BB6','#ED174C'],PHX:['#1D1160','#E56020'],POR:['#E03A3E','#000000'],
      SA:['#C4CED4','#000000'],SAC:['#5A2D81','#63727A'],TOR:['#CE1141','#000000'],UTAH:['#002B5C','#F9A01B'],WSH:['#002B5C','#E31837']},
    nhl:{ANA:['#F47A38','#B9975B'],BOS:['#FFB81C','#000000'],BUF:['#002654','#FCB514'],CAR:['#CE1126','#000000'],CBJ:['#002654','#CE1126'],
      CGY:['#C8102E','#F1BE48'],CHI:['#CF0A2C','#000000'],COL:['#6F263D','#236192'],DAL:['#006847','#8F8F8C'],DET:['#CE1126','#FFFFFF'],
      EDM:['#041E42','#FF4C00'],FLA:['#041E42','#C8102E'],LA:['#111111','#A2AAAD'],MIN:['#154734','#A6192E'],MTL:['#AF1E2D','#192168'],
      NJ:['#CE1126','#000000'],NSH:['#FFB81C','#041E42'],NYI:['#00539B','#F47D30'],NYR:['#0038A8','#CE1126'],OTT:['#C52032','#C2912C'],
      PHI:['#F74902','#000000'],PIT:['#000000','#FCB514'],SEA:['#001628','#99D9D9'],SJ:['#006D75','#EA7200'],STL:['#002F87','#FCB514'],
      TB:['#002868','#FFFFFF'],TOR:['#00205B','#FFFFFF'],UTA:['#69B3E7','#090909'],VAN:['#00205B','#00843D'],VGK:['#B4975A','#333F42'],
      WPG:['#041E42','#004C97'],WSH:['#041E42','#C8102E']},
    mlb:{ARI:['#A71930','#E3D4AD'],ATH:['#003831','#EFB21E'],ATL:['#CE1141','#13274F'],BAL:['#DF4601','#000000'],BOS:['#BD3039','#0C2340'],
      CHC:['#0E3386','#CC3433'],CHW:['#27251F','#C4CED4'],CIN:['#C6011F','#000000'],CLE:['#00385D','#E50022'],COL:['#33006F','#C4CED4'],
      DET:['#0C2340','#FA4616'],HOU:['#002D62','#EB6E1F'],KC:['#004687','#BD9B60'],LAA:['#BA0021','#003263'],LAD:['#005A9C','#EF3E42'],
      MIA:['#00A3E0','#EF3340'],MIL:['#12284B','#FFC52F'],MIN:['#002B5C','#D31145'],NYM:['#002D72','#FF5910'],NYY:['#0C2340','#C4CED4'],
      PHI:['#E81828','#002D72'],PIT:['#27251F','#FDB827'],SD:['#2F241D','#FFC425'],SEA:['#0C2C56','#005C5C'],SF:['#FD5A1E','#27251F'],
      STL:['#C41E3A','#0C2340'],TB:['#092C5C','#8FBCE6'],TEX:['#003278','#C0111F'],TOR:['#134A8E','#E8291C'],WSH:['#AB0003','#14225A']}
  };
  const lum = hex => { const n=parseInt(hex.slice(1),16), c=[n>>16&255,n>>8&255,n&255].map(v=>{ v/=255; return v<=.03928? v/12.92 : Math.pow((v+.055)/1.055,2.4); });
    return .2126*c[0]+.7152*c[1]+.0722*c[2]; };
  // CSS variables for a team-colored card: --tc1/--tc2 stripe + glow, --tcfg text on the primary.
  function teamVars(sport, abbr){
    const c=(TEAMS[sport]||{})[abbr] || ['#1f3a62','#3d5a86'];
    return `--tc1:${c[0]};--tc2:${c[1]};--tcfg:${lum(c[0])>.45?'#0b0b0b':'#ffffff'}`;
  }
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  // ---- countdowns: any element with data-cd="<ISO start>" reads "in 2h 14m" ----
  function until(ms){ const d=ms-Date.now(); if(d<=0) return 'under way';
    const m=Math.round(d/60000); if(m<60) return 'in '+m+'m';
    const h=Math.floor(m/60); return h<48? 'in '+h+'h '+(m%60)+'m' : 'in '+Math.round(h/24)+' days'; }
  function tickCountdowns(){ document.querySelectorAll('[data-cd]').forEach(e=>{ const t=Date.parse(e.dataset.cd); if(isFinite(t)) e.textContent=until(t); }); }
  setInterval(tickCountdowns, 30000);

  // ---- live ticker: #psticker scrolls the page's items, sports-TV style ----
  // items: [{ic, html, cls}] — html is trusted markup built by the page (escape data first).
  function ticker(items){
    const el=document.getElementById('psticker'); if(!el) return;
    if(!items || !items.length){ el.hidden=true; return; }
    const html=items.map(it=>`<span class="tk-item${it.cls?' '+it.cls:''}"><span class="tk-ic">${it.ic}</span>${it.html}</span>`).join('<span class="tk-sep">•</span>');
    if(el.dataset.sig===html){ el.hidden=false; return; }     // unchanged: keep it scrolling where it is
    el.dataset.sig=html;
    // two identical halves, so sliding the track by exactly -50% loops seamlessly
    const seq=`<span class="tk-seq">${html}<span class="tk-sep">•</span></span>`;
    el.innerHTML=`<div class="tk-live"><span class="tk-dot"></span>Live</div><div class="tk-view"><div class="tk-track">${seq}${seq}</div></div>`;
    el.hidden=false; tickCountdowns();
    setTimeout(()=>{ const tr=el.querySelector('.tk-track'); if(tr) tr.style.setProperty('--tkdur', Math.max(25, tr.scrollWidth/2/42)+'s'); }, 0);
  }

  // ---- loading shimmer: n placeholder cards shaped like pick cards ----
  function skeleton(n){
    let h='<div class="pickgrid" aria-busy="true" aria-label="Loading picks">';
    for(let i=0;i<n;i++) h+='<div class="pickcard skel"><div class="pc-top"><span class="sk sk-av"></span><div class="pc-who"><span class="sk sk-l1"></span><span class="sk sk-l2"></span></div><span class="sk sk-ring"></span></div><span class="sk sk-l3"></span><span class="sk sk-l4"></span></div>';
    return h+'</div>';
  }

  // ---- chance rings fill when they scroll into view (cards re-render, so watch the DOM) ----
  const io = ('IntersectionObserver' in window) ? new IntersectionObserver(es=>es.forEach(en=>{
    if(en.isIntersecting){ en.target.classList.add('on'); io.unobserve(en.target); } }), {threshold:.25}) : null;
  function watchRings(){
    const fresh=[...document.querySelectorAll('.pickcard .ring:not([data-w]), .verdict .ring:not([data-w])')];
    fresh.forEach(r=>{ r.dataset.w='1'; if(io) io.observe(r); else r.classList.add('on'); });
    // Safety net for browsers/webviews where the observer never reports: fill whatever is on screen.
    if(fresh.length) setTimeout(()=>fresh.forEach(r=>{ if(r.classList.contains('on')) return;
      const b=r.getBoundingClientRect(); if(b.bottom>0 && b.top<innerHeight){ r.classList.add('on'); if(io) io.unobserve(r); } }), 1200);
  }
  // ---- phones: Top 25 Surest shows 10 cards and a "Show all" button (app.css hides the rest) ----
  let edgesOpen=false;      // once opened, re-sorting keeps the full list
  function clampEdges(){
    const g=document.querySelector('#edgebody .pickgrid:not([aria-busy])'); if(!g || g.dataset.clamp) return;
    g.dataset.clamp='1';
    const n=g.querySelectorAll(':scope > .pickcard').length; if(n<=10) return;
    if(edgesOpen){ g.classList.add('all'); return; }
    const b=document.createElement('button'); b.type='button'; b.className='btn ghost showall'; b.textContent=`Show all ${n} ↓`;
    b.onclick=()=>{ edgesOpen=true; g.classList.add('all'); b.remove(); };
    g.after(b);
  }

  // ---- plain-English explainers: tap a term for one line on what it means ----
  const HELP={
    model:['Model %', "Our estimate of how often this bet wins — from the player's recent games, adjusted for the matchup. 71% means about 7 times in 10."],
    price:['Price', 'What one share costs on Polymarket. A share pays $1 if the bet wins, so a 43¢ price also means the market sees it as a 43% chance.'],
    payout:['Payout', 'What you get back for each $1 if it wins, your stake included. 2.33× means a $10 bet returns $23.30.'],
    edge:['Edge', "The model's chance minus the market's, in points. +28 means we rate it 28 points likelier than the price says. Bigger is better — but it's an estimate, not a promise."],
    last10:['Last 10', "The player's last ten games at this line: green bars cleared it, red ones didn't, and the dashed mark is the line. \"7/10\" = cleared it 7 times."],
    range:['Range · games', 'The first numbers are where the true chance most likely sits (80% range); "12g" is how many games it\'s based on. Wide range or few games = less certain.'],
    value:['Value spots', 'Bets where Polymarket gives at least a 30% chance and our model is 15+ points higher. The best bets for the price — not the surest ones.'],
    surest:['Top 25 Surest', "The likeliest bets on the board, whatever they pay. Likely isn't certain: they still lose sometimes, and at 85–97¢ a single loss wipes out several wins."],
  };
  const helpBtn=(k,label)=>`<button type="button" class="qhelp" data-help="${k}" aria-expanded="false">${label}<span class="qi" aria-hidden="true">?</span></button>`;
  function legend(short){
    return `<div class="pslegend"><span class="lg-lab">How to read a card</span>${helpBtn('model','Model %')}${helpBtn('last10','Last 10')}${helpBtn('price','Price')}${helpBtn('payout','Payout')}${helpBtn('edge','Edge')}${short?'':helpBtn('range','Range')}</div>`;
  }
  // One legend per page, just above the first real grid of pick cards. Boards render at
  // different times (NFL's leaderboard at once, Value spots after the live scan), so it
  // moves up when a grid appears above it.
  function placeLegend(){
    const root=document.querySelector('#page-week, #today'); if(!root) return;
    const g=[...root.querySelectorAll('.pickgrid:not([aria-busy])')].find(x=>x.querySelector('.pickcard') && !x.closest('.collapsed')); if(!g) return;
    const cur=root.querySelector('.pslegend');
    if(cur && cur.nextElementSibling===g) return;
    if(cur) cur.remove();
    g.insertAdjacentHTML('beforebegin', legend(!!g.closest('#today')));
  }
  let pop=null;
  function closeHelp(){ if(!pop) return; pop.remove(); pop=null;
    document.querySelectorAll('.qhelp[aria-expanded="true"]').forEach(b=>{ b.setAttribute('aria-expanded','false'); b.removeAttribute('aria-describedby'); }); }
  // Capture phase: runs before a collapsible panel header or a card link sees the tap.
  document.addEventListener('click', e=>{
    const b=e.target.closest && e.target.closest('.qhelp');
    if(!b){ if(pop && !pop.contains(e.target)) closeHelp(); return; }
    e.preventDefault(); e.stopPropagation();
    const wasOpen=b.getAttribute('aria-expanded')==='true'; closeHelp(); if(wasOpen) return;
    const h=HELP[b.dataset.help]; if(!h) return;
    pop=document.createElement('div'); pop.className='pshelp'; pop.id='pshelp'; pop.setAttribute('role','tooltip');
    pop.innerHTML=`<b>${esc(h[0])}</b>${esc(h[1])}`;
    const w=Math.min(300, innerWidth-24); pop.style.width=w+'px';
    document.body.appendChild(pop);
    const r=b.getBoundingClientRect();
    const left=Math.max(12, Math.min(r.left+r.width/2-w/2, innerWidth-w-12));
    let top=r.bottom+8; if(top+pop.offsetHeight>innerHeight-8 && r.top-pop.offsetHeight-8>0) top=r.top-pop.offsetHeight-8;
    pop.style.left=(left+scrollX)+'px'; pop.style.top=(top+scrollY)+'px';
    b.setAttribute('aria-expanded','true'); b.setAttribute('aria-describedby','pshelp');
  }, true);
  document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeHelp(); });
  addEventListener('resize', closeHelp);

  // Icon shapes: Lucide (lucide.dev) plus hand-drawn sport glyphs and Instagram. 24×24, stroked.
  // Lucide: Copyright (c) 2026 Lucide Icons and Contributors, ISC License; some icons derive from Feather,
  // Copyright (c) 2013-present Cole Bemis, MIT License. Full notices: LICENSE-lucide-icons.txt.
  const ICONS={"calendar-days":"<path d=\"M8 2v3\"/><path d=\"M16 2v3\"/><rect x=\"3\" y=\"3\" width=\"18\" height=\"18\" rx=\"2\"/><path d=\"M3 9h18\"/><path d=\"M8 13h.01\"/><path d=\"M12 13h.01\"/><path d=\"M16 13h.01\"/><path d=\"M8 17h.01\"/><path d=\"M12 17h.01\"/><path d=\"M16 17h.01\"/>","microscope":"<path d=\"M6 18h8\"/><path d=\"M3 22h18\"/><path d=\"M14 22a7 7 0 1 0 0-14h-1\"/><path d=\"M9 14h2\"/><path d=\"M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2Z\"/><path d=\"M12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3\"/>","wrench":"<path d=\"M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.106-3.105c.32-.322.863-.22.983.218a6 6 0 0 1-8.259 7.057l-7.91 7.91a1 1 0 0 1-2.999-3l7.91-7.91a6 6 0 0 1 7.057-8.259c.438.12.54.662.219.984z\"/>","notebook-text":"<path d=\"M2 6h4\"/><path d=\"M2 10h4\"/><path d=\"M2 14h4\"/><path d=\"M2 18h4\"/><rect width=\"16\" height=\"20\" x=\"4\" y=\"2\" rx=\"2\"/><path d=\"M9.5 8h5\"/><path d=\"M9.5 12H16\"/><path d=\"M9.5 16H14\"/>","newspaper":"<path d=\"M15 18h-5\"/><path d=\"M18 14h-8\"/><path d=\"M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-4 0v-9a2 2 0 0 1 2-2h2\"/><rect width=\"8\" height=\"4\" x=\"10\" y=\"6\" rx=\"1\"/>","camera":"<path d=\"M13.997 4a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 1.759-1.048l.489-.904A2 2 0 0 1 10.004 4z\"/><circle cx=\"12\" cy=\"13\" r=\"3\"/>","lock":"<rect width=\"18\" height=\"11\" x=\"3\" y=\"11\" rx=\"2\" ry=\"2\"/><path d=\"M7 11V7a5 5 0 0 1 10 0v4\"/>","zap":"<path d=\"M15.914 4a1.5 1.5 0 00-2.474-1.561l-9 9A1.5 1.5 0 005.5 14h4.002a.5.5 0 01.471.666L8.086 20a1.5 1.5 0 002.475 1.56l9-9A1.5 1.5 0 0018.5 10h-3.997a.5.5 0 01-.472-.667z\"/>","flame":"<path d=\"M12 3q1 4 4 6.5t3 5.5a1 1 0 0 1-14 0 5 5 0 0 1 1-3 1 1 0 0 0 5 0c0-2-1.5-3-1.5-5q0-2 2.5-4\"/>","star":"<path d=\"M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z\"/>","scale":"<path d=\"M12 3v18\"/><path d=\"m19 8 3 8a5 5 0 0 1-6 0zV7\"/><path d=\"M3 7h1a17 17 0 0 0 8-2 17 17 0 0 0 8 2h1\"/><path d=\"m5 8 3 8a5 5 0 0 1-6 0zV7\"/><path d=\"M7 21h10\"/>","dices":"<rect width=\"12\" height=\"12\" x=\"2\" y=\"10\" rx=\"2\" ry=\"2\"/><path d=\"m17.92 14 3.5-3.5a2.24 2.24 0 0 0 0-3l-5-4.92a2.24 2.24 0 0 0-3 0L10 6\"/><path d=\"M6 18h.01\"/><path d=\"M10 14h.01\"/><path d=\"M15 6h.01\"/><path d=\"M18 9h.01\"/>","receipt":"<path d=\"M12 17V7\"/><path d=\"M16 8h-6a2 2 0 0 0 0 4h4a2 2 0 0 1 0 4H8\"/><path d=\"M4 3a1 1 0 0 1 1-1 1.3 1.3 0 0 1 .7.2l.933.6a1.3 1.3 0 0 0 1.4 0l.934-.6a1.3 1.3 0 0 1 1.4 0l.933.6a1.3 1.3 0 0 0 1.4 0l.933-.6a1.3 1.3 0 0 1 1.4 0l.934.6a1.3 1.3 0 0 0 1.4 0l.933-.6A1.3 1.3 0 0 1 19 2a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1 1.3 1.3 0 0 1-.7-.2l-.933-.6a1.3 1.3 0 0 0-1.4 0l-.934.6a1.3 1.3 0 0 1-1.4 0l-.933-.6a1.3 1.3 0 0 0-1.4 0l-.933.6a1.3 1.3 0 0 1-1.4 0l-.934-.6a1.3 1.3 0 0 0-1.4 0l-.933.6a1.3 1.3 0 0 1-.7.2 1 1 0 0 1-1-1z\"/>","lightbulb":"<path d=\"M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5\"/><path d=\"M9 18h6\"/><path d=\"M10 22h4\"/>","gift":"<path d=\"M12 7v14\"/><path d=\"M20 11v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8\"/><path d=\"M7.5 7a1 1 0 0 1 0-5A4.8 8 0 0 1 12 7a4.8 8 0 0 1 4.5-5 1 1 0 0 1 0 5\"/><rect x=\"3\" y=\"7\" width=\"18\" height=\"4\" rx=\"1\"/>","users":"<path d=\"M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2\"/><path d=\"M16 3.128a4 4 0 0 1 0 7.744\"/><path d=\"M22 21v-2a4 4 0 0 0-3-3.87\"/><circle cx=\"9\" cy=\"7\" r=\"4\"/>","link":"<path d=\"M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71\"/><path d=\"M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71\"/>","plus":"<path d=\"M5 12h14\"/><path d=\"M12 5v14\"/>","timer":"<line x1=\"10\" x2=\"14\" y1=\"2\" y2=\"2\"/><line x1=\"12\" x2=\"15\" y1=\"14\" y2=\"11\"/><circle cx=\"12\" cy=\"14\" r=\"8\"/>","hourglass":"<path d=\"M5 22h14\"/><path d=\"M5 2h14\"/><path d=\"M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22\"/><path d=\"M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2\"/>","chart-column":"<path d=\"M3 3v16a2 2 0 0 0 2 2h16\"/><path d=\"M18 17V9\"/><path d=\"M13 17V5\"/><path d=\"M8 17v-3\"/>","circle-check":"<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"m16 9-5.5 5.5L8 12\"/>","layout-grid":"<rect width=\"7\" height=\"7\" x=\"3\" y=\"3\" rx=\"1\"/><rect width=\"7\" height=\"7\" x=\"14\" y=\"3\" rx=\"1\"/><rect width=\"7\" height=\"7\" x=\"14\" y=\"14\" rx=\"1\"/><rect width=\"7\" height=\"7\" x=\"3\" y=\"14\" rx=\"1\"/>","badge-check":"<path d=\"M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z\"/><path d=\"m16 9-5.5 5.5L8 12\"/>","target":"<circle cx=\"12\" cy=\"12\" r=\"10\"/><circle cx=\"12\" cy=\"12\" r=\"6\"/><circle cx=\"12\" cy=\"12\" r=\"2\"/>","ban":"<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M4.929 4.929 19.07 19.071\"/>","triangle-alert":"<path d=\"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3\"/><path d=\"M12 9v4\"/><path d=\"M12 17h.01\"/>","trending-up":"<path d=\"M16 7h6v6\"/><path d=\"m22 7-8.5 8.5-5-5L2 17\"/>","calculator":"<rect width=\"16\" height=\"20\" x=\"4\" y=\"2\" rx=\"2\"/><line x1=\"8\" x2=\"16\" y1=\"6\" y2=\"6\"/><line x1=\"16\" x2=\"16\" y1=\"14\" y2=\"18\"/><path d=\"M16 10h.01\"/><path d=\"M12 10h.01\"/><path d=\"M8 10h.01\"/><path d=\"M12 14h.01\"/><path d=\"M8 14h.01\"/><path d=\"M12 18h.01\"/><path d=\"M8 18h.01\"/>","sliders-horizontal":"<path d=\"M10 5H3\"/><path d=\"M12 19H3\"/><path d=\"M14 3v4\"/><path d=\"M16 17v4\"/><path d=\"M21 12h-9\"/><path d=\"M21 19h-5\"/><path d=\"M21 5h-7\"/><path d=\"M8 10v4\"/><path d=\"M8 12H3\"/>","ruler":"<path d=\"M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.41 2.41 0 0 1 0-3.4l2.6-2.6a2.41 2.41 0 0 1 3.4 0Z\"/><path d=\"m14.5 12.5 2-2\"/><path d=\"m11.5 9.5 2-2\"/><path d=\"m8.5 6.5 2-2\"/><path d=\"m17.5 15.5 2-2\"/>","handshake":"<path d=\"m11 17 2 2a1 1 0 1 0 3-3\"/><path d=\"m14 14 2.5 2.5a1 1 0 1 0 3-3l-3.88-3.88a3 3 0 0 0-4.24 0l-.88.88a1 1 0 1 1-3-3l2.81-2.81a5.79 5.79 0 0 1 7.06-.87l.47.28a2 2 0 0 0 1.42.25L21 4\"/><path d=\"m21 3 1 11h-2\"/><path d=\"M3 3 2 14l6.5 6.5a1 1 0 1 0 3-3\"/><path d=\"M3 4h8\"/>","search":"<path d=\"m21 21-4.34-4.34\"/><circle cx=\"11\" cy=\"11\" r=\"8\"/>","brain":"<path d=\"M12 18V5\"/><path d=\"M15 13a4.17 4.17 0 0 1-3-4 4.17 4.17 0 0 1-3 4\"/><path d=\"M17.598 6.5A3 3 0 1 0 12 5a3 3 0 1 0-5.598 1.5\"/><path d=\"M17.997 5.125a4 4 0 0 1 2.526 5.77\"/><path d=\"M18 18a4 4 0 0 0 2-7.464\"/><path d=\"M19.967 17.483A4 4 0 1 1 12 18a4 4 0 1 1-7.967-.517\"/><path d=\"M6 18a4 4 0 0 1-2-7.464\"/><path d=\"M6.003 5.125a4 4 0 0 0-2.526 5.77\"/>","bandage":"<path d=\"M10 10.01h.01\"/><path d=\"M10 14.01h.01\"/><path d=\"M14 10.01h.01\"/><path d=\"M14 14.01h.01\"/><path d=\"M18 6v12\"/><path d=\"M6 6v12\"/><rect x=\"2\" y=\"6\" width=\"20\" height=\"12\" rx=\"2\"/>","settings":"<path d=\"M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915\"/><circle cx=\"12\" cy=\"12\" r=\"3\"/>","music-2":"<circle cx=\"8\" cy=\"18\" r=\"4\"/><path d=\"M12 18V2l7 4\"/>","shield-check":"<path d=\"M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z\"/><path d=\"m9 12 2 2 4-4\"/>","football":"<ellipse cx=\"12\" cy=\"12\" rx=\"10\" ry=\"6\" transform=\"rotate(-45 12 12)\"/><path d=\"M9.2 14.8l5.6-5.6\"/><path d=\"M10.4 11.6l2 2\"/><path d=\"M11.6 10.4l2 2\"/>","basketball":"<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M2 12h20\"/><path d=\"M12 2v20\"/><path d=\"M5 4.9c2.3 2 3.5 4.5 3.5 7.1S7.3 17.1 5 19.1\"/><path d=\"M19 4.9c-2.3 2-3.5 4.5-3.5 7.1s1.2 5.1 3.5 7.1\"/>","baseball":"<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M6.2 5.2c1.9 1.8 3 4.2 3 6.8s-1.1 5-3 6.8\"/><path d=\"M17.8 5.2c-1.9 1.8-3 4.2-3 6.8s1.1 5 3 6.8\"/>","hockey":"<path d=\"M5 3l7.2 13.2a1.5 1.5 0 0 0 1.3.8H21\"/><path d=\"M21 17v3h-7.7a3 3 0 0 1-2.6-1.6L3 4.5\"/><ellipse cx=\"5.5\" cy=\"19.5\" rx=\"3\" ry=\"1.5\"/>","instagram":"<rect x=\"3\" y=\"3\" width=\"18\" height=\"18\" rx=\"5\"/><circle cx=\"12\" cy=\"12\" r=\"4\"/><circle cx=\"17.5\" cy=\"6.5\" r=\"1\" fill=\"currentColor\" stroke=\"none\"/>","star-fill":"<path fill=\"currentColor\" d=\"M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z\"/>"};
  const icon=(name, cls)=> ICONS[name]? `<svg class="ic${cls?' '+cls:''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICONS[name]}</svg>` : '';

  // ---- one icon set instead of emoji: the pages' text still says "⚡ Value spots", and this swaps
  // each known emoji for its icon as content appears (headings, tabs, buttons, ticker, summaries). ----
  const EMOJI={'📅':'calendar-days','🔬':'microscope','🧰':'wrench','📒':'notebook-text','📰':'newspaper','📸':'camera','🔒':'lock','⚡':'zap',
    '🔥':'flame','⭐':'star','☆':'star','★':'star-fill','⚖':'scale','🎲':'dices','🧾':'receipt','💡':'lightbulb','🎁':'gift','👥':'users','🔗':'link',
    '➕':'plus','⏱':'timer','⏳':'hourglass','📊':'chart-column','✅':'circle-check','🏟':'layout-grid','💯':'badge-check','🎯':'target','⛔':'ban',
    '⚠':'triangle-alert','📈':'trending-up','🧮':'calculator','🎚':'sliders-horizontal','📏':'ruler','🤝':'handshake','🔍':'search','🧠':'brain',
    '🩹':'bandage','⚙':'settings','🎵':'music-2','🏈':'football','🏀':'basketball','🏒':'hockey','⚾':'baseball'};
  const EMOJI_RE=new RegExp('('+Object.keys(EMOJI).join('|')+')\ufe0f?( ?)','gu');   // a trailing space becomes the icon's margin
  const SKIP='script,style,textarea,input,select,option,svg,canvas,[data-noicon]';
  function iconifyText(t){
    const s=t.nodeValue; EMOJI_RE.lastIndex=0; if(!EMOJI_RE.test(s)) return;
    const p=t.parentNode; if(!p || (p.closest && p.closest(SKIP))) return;
    const frag=document.createDocumentFragment(); let last=0; EMOJI_RE.lastIndex=0; let m;
    while((m=EMOJI_RE.exec(s))){
      if(m.index>last) frag.appendChild(document.createTextNode(s.slice(last, m.index)));
      const tpl=document.createElement('template'); tpl.innerHTML=icon(EMOJI[m[1]], m[2]? 'sp' : ''); frag.appendChild(tpl.content.firstChild);
      last=m.index+m[0].length;
    }
    if(last<s.length) frag.appendChild(document.createTextNode(s.slice(last)));
    p.replaceChild(frag, t);
  }
  function iconify(root){
    if(!root) return;
    if(root.nodeType===3){ iconifyText(root); return; }
    if(root.nodeType!==1 || root.closest(SKIP)) return;
    // never scan <script>/<style> text: the sport pages carry 2–4 MB of data in one script
    const w=document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {acceptNode:n=>{ const t=n.parentNode && n.parentNode.nodeName;
      return t==='SCRIPT' || t==='STYLE' || t==='TEXTAREA'? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT; }}), hits=[];
    while(w.nextNode()){ EMOJI_RE.lastIndex=0; if(EMOJI_RE.test(w.currentNode.nodeValue)) hits.push(w.currentNode); }
    hits.forEach(iconifyText);
  }
  if(document.readyState!=='loading') iconify(document.body); else document.addEventListener('DOMContentLoaded', ()=>iconify(document.body));

  let queued=false, added=[];
  new MutationObserver(recs=>{
    recs.forEach(r=>{ if(r.type==='characterData') added.push(r.target);
      else r.addedNodes.forEach(n=>{ if(n.nodeName!=='SCRIPT' && n.nodeName!=='STYLE' && !(n.nodeType===3 && n.parentNode && n.parentNode.nodeName==='SCRIPT')) added.push(n); }); });
    if(queued) return; queued=true;
    setTimeout(()=>{ queued=false; const batch=added; added=[]; batch.forEach(n=>{ if(n.isConnected) iconify(n); });
      watchRings(); clampEdges(); placeLegend(); }, 60); })
    .observe(document.documentElement, {childList:true, subtree:true, characterData:true});

  // ---- hover spotlight: the card's glow follows the pointer ----
  document.addEventListener('pointermove', e=>{
    const c=e.target && e.target.closest && e.target.closest('.pickcard'); if(!c) return;
    const r=c.getBoundingClientRect(); c.style.setProperty('--mx', (e.clientX-r.left)+'px'); c.style.setProperty('--my', (e.clientY-r.top)+'px');
  }, {passive:true});

  // ---- shareable pick links: #player/<id>/<stat>/<line>/<side>/<name-slug> ----
  // The slug is only there so a pasted link reads as a name; parsing ignores it.
  const slug = s => String(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
  const hashFor = (id, stat, line, side, name) => `player/${encodeURIComponent(id)}/${stat}/${line}/${side}/${slug(name)}`;
  function pickHash(st){
    if(!st || !st.player) return 'player';
    return hashFor(st.player.id, st.stat, st.line, st.ou, st.player.n);
  }
  function parsePickHash(h){
    const m=/^#?player\/([^/]+)\/([a-z0-9_]+)\/(\d+(?:\.\d+)?)\/(over|under)\b/i.exec(h||'');
    return m? {id:decodeURIComponent(m[1]), stat:m[2], line:parseFloat(m[3]), ou:m[4].toLowerCase()} : null;
  }
  // Keep the address bar on the prop being researched, so copying the URL shares it too.
  function syncHash(st){
    const pg=document.getElementById('page-player'); if(!pg || pg.hidden) return;
    // Phones show the stat buttons as one swipeable row: keep the selected one in view.
    const row=document.getElementById('chips'), on=row && row.querySelector('.chip[aria-pressed="true"]');
    if(on && row.scrollWidth>row.clientWidth) row.scrollLeft=Math.max(0, on.offsetLeft-row.offsetLeft-40);
    const h='#'+pickHash(st); if(location.hash===h) return;
    try{ history.replaceState(null,'',h); }catch(e){}
  }
  function toast(msg){
    let t=document.getElementById('pstoast');
    if(!t){ t=document.createElement('div'); t.id='pstoast'; t.className='pstoast'; t.setAttribute('role','status'); document.body.appendChild(t); }
    t.textContent=msg; t.classList.add('on'); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove('on'), 2200);
  }
  // Phones get the native share sheet; everywhere else the link is copied.
  function sharePick(st, statText){
    if(!st || !st.player) return;
    const url=location.origin+location.pathname+'#'+pickHash(st);
    const text=`${st.player.n} ${st.ou} ${st.line} ${statText||st.stat} — the model's chance, the game log and the live price`;
    const touch=window.matchMedia && matchMedia('(pointer:coarse)').matches;
    if(touch && navigator.share){ navigator.share({title:'Prop Streak Lab', text, url}).catch(()=>{}); return; }
    const done=()=>toast('🔗 Link copied — paste it anywhere');
    if(navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(url).then(done, ()=>window.prompt('Copy this link:', url));
    else window.prompt('Copy this link:', url);
  }

  // ---- mini "last 10" chart for a pick card: green bars cleared the line, red didn't ----
  function spark(vals, line, side){
    const v=(vals||[]).filter(x=>x!=null && isFinite(x)).slice(-10); line=+line;
    if(v.length<3 || !isFinite(line)) return '';
    const clears=x=> side==='under'? x<line : x>line;
    const top=Math.max(line*1.6, ...v, 1), hits=v.filter(clears).length;
    const bars=v.map(x=>`<i class="${x===line?'push':clears(x)?'hit':'miss'}" style="height:${Math.max(9, Math.round(100*x/top))}%"></i>`).join('');
    return `<span class="spark" role="img" aria-label="Last ${v.length} games: cleared ${line} ${hits} times">`+
      `<span class="sp-bars">${bars}<em style="bottom:${Math.round(100*line/top)}%"></em></span><span class="sp-n">${hits}/${v.length}</span></span>`;
  }

  // ---- the Player tab's verdict card: the model's chance against the price, in one call ----
  // VALUE uses the site's own two rules (price 30¢+, model 15+ points better); SKIP means
  // the price is above the model's chance; FAIR is everything between.
  function verdictOf(prob, price){
    const pv=Math.round(prob*100);
    if(price==null) return {k:'none', label:'No price', say:"No Polymarket price for this exact line right now — the model's chance stands on its own. Check the price before you bet."};
    const c=Math.round(price*100), e=Math.round((prob-price)*100), sg=(e>=0?'+':'−')+Math.abs(e);
    if(price>=0.30 && prob-price>=0.15) return {k:'value', label:'Value', say:`Polymarket prices it at ${c}% and the model says ${pv}% — ${e} points better, which clears both value rules.`};
    const an=/^(8|11|18)/.test(String(c))? 'an' : 'a';   // "an 80% chance", "a 60% chance"
    if(prob-price<=-0.03) return {k:'skip', label:'Skip', say:`At ${c}¢ you'd be paying for ${an} ${c}% chance, and the model only gives it ${pv}%. Overpriced.`};
    if(price<0.30 && prob-price>=0.15) return {k:'fair', label:'Fair', say:`Big edge on paper (${sg}), but at ${c}¢ it's a longshot — the value rules skip anything under 30¢.`};
    if(e>=15) return {k:'fair', label:'Fair', say:`Right on the value bar (${sg}) but not clearly over it — the model's ${pv}% against ${c}¢.`};
    return {k:'fair', label:'Fair', say:`Priced close to the model's ${pv}% — an edge of ${sg} points, short of the +15 it takes to call it value.`};
  }
  // o: {prob, lo, hi, neff, side, line, statText, price, live, marketLine, onShare} — or null to hide.
  function verdict(el, o){
    if(!el) return;
    if(!o || o.prob==null){ el.hidden=true; return; }       // keep the markup, so re-showing it doesn't replay the ring
    const pv=Math.round(o.prob*100), v=verdictOf(o.prob, o.price);
    const c=o.price!=null? Math.round(o.price*100) : null, e=c!=null? Math.round((o.prob-o.price)*100) : null;
    const tier=o.prob>=0.9?'hi':o.prob>=0.7?'mid':'lo';
    const sig=[pv,o.side,o.line,o.statText,c,v.k,o.live,o.marketLine].join('|');
    if(el.dataset.sig!==sig){
      el.dataset.sig=sig;
      el.className=`verdict v-${v.k} t-${tier}`;
      const stats = c!=null
        ? `<div class="vd-stats"><span><b>${c}¢</b>${o.live? '<i class="vd-live">● live price</i>' : 'price · last update'}</span>`+
          `<span><b>${(1/o.price).toFixed(2)}×</b>payout</span><span><b class="${e>=0?'pos':'neg'}">${e>=0?'+':'−'}${Math.abs(e)}</b>edge</span></div>`
        : (o.marketLine!=null? `<div class="vd-stats"><span class="vd-note">Polymarket lists this prop at <b>${esc(o.marketLine)}</b> — set the line to ${esc(o.marketLine)} to compare.</span></div>` : '');
      const range=o.lo!=null? `${Math.round(o.lo*100)}–${Math.round(o.hi*100)}% range` : '';
      const games=o.neff? `${Math.round(o.neff)} games` : '';
      el.innerHTML=`<div class="ring" style="--p:${pv}"><b>${pv}<small>%</small></b></div>`+
        `<div class="vd-main"><div class="vd-top"><span class="vd-chip">${v.label}</span><span class="vd-cap">Model chance${range?' · '+range:''}${games?' · '+games:''}</span></div>`+
          `<div class="vd-bet"><span class="leantag ${esc(o.side)}">${esc(o.side)}</span><b>${esc(o.line)}</b><span>${esc(o.statText)}</span></div>`+
          stats+`<p class="vd-say">${esc(v.say)}</p></div>`+
        `<button type="button" class="btn ghost vd-share">🔗 Share</button>`;
    }
    const sb=el.querySelector('.vd-share'); if(sb) sb.onclick=o.onShare||null;
    el.hidden=false;
  }

  // ---- pop-up sheet: slides up on phones, a centred card on desktop ----
  let sheetEl=null, sheetPrev=null;
  function closeSheet(){ if(!sheetEl) return; sheetEl.remove(); sheetEl=null; document.documentElement.classList.remove('ps-lock');
    if(sheetPrev && sheetPrev.focus) sheetPrev.focus({preventScroll:true}); sheetPrev=null; }
  function sheet(html, label){
    closeSheet(); sheetPrev=document.activeElement;
    const w=document.createElement('div'); w.className='pssheet app';
    w.innerHTML=`<div class="ps-back" data-close></div><div class="ps-card" role="dialog" aria-modal="true" aria-label="${esc(label||'Details')}">`+
      `<button type="button" class="ps-x" data-close aria-label="Close">✕</button>${html}</div>`;
    w.addEventListener('click', e=>{ if(e.target.closest('[data-close]')) closeSheet(); });
    document.body.appendChild(w); sheetEl=w; document.documentElement.classList.add('ps-lock');
    (w.querySelector('.ps-card .ps-open') || w.querySelector('.ps-x')).focus({preventScroll:true});
    return w;
  }
  document.addEventListener('keydown', e=>{
    if(!sheetEl) return;
    if(e.key==='Escape'){ closeSheet(); return; }
    if(e.key==='Tab'){   // keep focus inside the sheet
      const f=[...sheetEl.querySelectorAll('button,a[href]')].filter(x=>!x.hidden && x.offsetParent!==null); if(!f.length) return;
      const i=f.indexOf(document.activeElement);
      if(e.shiftKey && i<=0){ e.preventDefault(); f[f.length-1].focus(); } else if(!e.shiftKey && i===f.length-1){ e.preventDefault(); f[0].focus(); }
    }
  });
  const num=x=> Number.isInteger(x)? String(x) : x.toFixed(1);
  function bigSpark(vals, line, side){
    const v=(vals||[]).filter(x=>x!=null && isFinite(x)).slice(-10); line=+line; if(v.length<3) return '';
    const clears=x=> side==='under'? x<line : x>line, top=Math.max(line*1.6, ...v, 1), H=86;
    return `<div class="ps-bars" style="--h:${H}px">`+v.map(x=>`<span class="${x===line?'push':clears(x)?'hit':'miss'}"><i style="height:${Math.max(3, Math.round(H*x/top))}px"></i><em>${num(x)}</em></span>`).join('')+
      `<b class="ps-line" style="bottom:${20+Math.round(H*line/top)}px"><small>${num(line)}</small></b></div>`;
  }
  const initialsOf=n=>{ const w=String(n||'').replace(/\s+(Jr|Sr|II|III|IV)\.?$/i,'').trim().split(/\s+/); return ((w[0]||'')[0]||'')+(w.length>1? (w[w.length-1][0]||'') : ''); };
  // A pick card's details: the verdict, the last 10 games, then the full breakdown or share.
  // o: {name, team, sport, vs, when, prob, lo, hi, neff, side, line, statText, price, live, vals, onOpen, onShare}
  function pickSheet(o){
    const v=(o.vals||[]).filter(x=>x!=null && isFinite(x)).slice(-10), hits=v.filter(x=> o.side==='under'? x<+o.line : x>+o.line).length;
    const w=sheet(`<div class="ps-head" style="${teamVars(o.sport, o.team)}"><span class="av">${esc(initialsOf(o.name))}</span>`+
        `<div><b>${esc(o.name)}</b><span><span class="tbadge">${esc(o.team)}</span>${esc(o.vs||'')}${o.when? ' · '+esc(o.when) : ''}</span></div></div>`+
      `<div class="verdict" hidden></div>`+
      (v.length>=3? `<div class="ps-l10"><div class="ps-sub">Last ${v.length} games · cleared ${esc(o.line)} <b>${hits} of ${v.length}</b></div>${bigSpark(v, o.line, o.side)}</div>` : '')+
      `<div class="ps-actions"><button type="button" class="btn ps-open">Full breakdown →</button></div>`,
      `${o.name} ${o.side} ${o.line} ${o.statText}`);
    verdict(w.querySelector('.verdict'), o);
    w.querySelector('.ps-open').onclick=()=>{ closeSheet(); if(o.onOpen) o.onOpen(); };
  }

  // ---- one-time 18+ check. It carries the storage notice, so a first visit sees one pop-up, not two. ----
  function ageGate(){
    let ok=false; try{ ok=localStorage.getItem('psl_age_ok')==='1'; }catch(e){}
    if(ok || !document.body) return;
    const g=document.createElement('div'); g.className='psgate'; g.setAttribute('role','dialog'); g.setAttribute('aria-modal','true'); g.setAttribute('aria-labelledby','psgate-h');
    g.innerHTML=`<div class="psgate-card"><svg class="psgate-logo" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14" fill="#0f2038"/><path d="M32,6 Q32,32 54,32 Q32,32 32,58 Q32,32 10,32 Q32,32 32,6 Z" fill="#22d07f"/></svg>`+
      `<h2 id="psgate-h">Are you 18 or older?</h2>`+
      `<p>Prop Streak Lab is player-prop research for adults. It isn't a sportsbook and takes no bets. Some links go to Polymarket, which has its own age and location rules.</p>`+
      `<div class="psgate-btns"><button type="button" class="btn" id="psgate-ok">Yes, I'm 18 or older</button><a class="btn ghost" href="https://www.google.com" rel="noopener">No, leave</a></div>`+
      `<p class="psgate-fine">We use only essential local storage for your preferences and cookieless analytics — no ads, no cross-site tracking. <a href="cookies.html">Cookie Policy</a> · <a href="privacy.html">Privacy</a><br>Gambling problem? Call 1-800-522-4700 or visit <a href="https://www.ncpgambling.org" rel="noopener" target="_blank">ncpgambling.org</a>.</p></div>`;
    document.body.appendChild(g); document.documentElement.classList.add('ps-lock');
    const bar=document.getElementById('pslcookie'); if(bar) bar.hidden=true;    // the check carries the same notice
    const btn=g.querySelector('#psgate-ok'); btn.focus({preventScroll:true});
    btn.onclick=()=>{ try{ localStorage.setItem('psl_age_ok','1'); localStorage.setItem('psl_notice_ok','1'); }catch(e){}
      g.remove(); document.documentElement.classList.remove('ps-lock'); };
  }
  if(document.readyState!=='loading') ageGate(); else document.addEventListener('DOMContentLoaded', ageGate);

  // ---- trust line under each hero: when the data last updated, and how many picks are graded in public ----
  // Both come from today.json, which the hourly job rewrites on every run.
  function ago(ms){ const m=Math.max(0, Math.round((Date.now()-ms)/60000));
    if(m<1) return 'just now'; if(m<60) return m+' min ago'; const h=Math.round(m/60); return h<48? h+(h===1?' hour':' hours')+' ago' : Math.round(h/24)+' days ago'; }
  function trust(){
    const el=document.getElementById('pstrust'); if(!el) return;
    const paint=t=>{
      let upd=t && Date.parse(t.gen);
      if(!isFinite(upd)){ const lm=Date.parse(document.lastModified); upd= isFinite(lm) && lm<=Date.now()+6e4 && Date.now()-lm<30*864e5? lm : null; }
      const tr=t && t.tracked, since=tr && tr.since? new Date(tr.since+'T12:00:00Z').toLocaleDateString('en-US',{month:'short', day:'numeric', year:'numeric'}) : '';
      el.innerHTML=(upd? `<span class="tr-upd"><i class="tr-dot" aria-hidden="true"></i>Updated <b data-ago="${upd}">${ago(upd)}</b></span>` : '')+
        (tr && tr.graded? `<span class="tr-grd">${icon('shield-check')}<b>${tr.graded.toLocaleString('en-US')} picks graded in public</b>${since? ' since '+esc(since) : ''}</span>` : '')+
        `<a class="tr-how" href="methodology.html">How the model works →</a>`;
      el.hidden=false;
    };
    paint(null);
    fetch('today.json',{cache:'no-store'}).then(r=>r.ok? r.json() : null).then(t=>{ if(t) paint(t); }).catch(()=>{});
    setInterval(()=>el.querySelectorAll('[data-ago]').forEach(b=>{ b.textContent=ago(+b.dataset.ago); }), 60000);
  }
  if(document.readyState!=='loading') trust(); else document.addEventListener('DOMContentLoaded', trust);

  return {teamVars, ticker, until, skeleton, esc, hashFor, pickHash, parsePickHash, syncHash, sharePick, toast, helpBtn, spark, verdict, icon, sheet, closeSheet, pickSheet};
})();
