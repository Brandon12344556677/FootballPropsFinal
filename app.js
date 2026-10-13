/* Prop Streak Lab — shared "app" behavior for the sport boards and the home page:
   team colors, the live ticker (with countdowns), chance-ring animation, loading
   shimmer and the hover spotlight on pick cards. Pages call PS.teamVars(),
   PS.ticker(items) and PS.skeleton(n); everything else runs by itself. Pairs with
   app.css. Its only network calls are anonymous counts to GoatCounter: time on page and
   clicks on links that leave the site (bottom). */
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
    edge:['Edge', "The model's chance minus the market's, in points. On the graded record the market has predicted better than the model, so read it next to the fair chance — the realistic edge is much smaller."],
    fair:['Fair chance', "The model's chance blended with the Polymarket price, weighted by how well each has predicted every graded pick so far. Right now that's mostly market: prices already reflect injuries and news the model can't see. It's the most realistic number on the card."],
    last10:['Last 10', "The player's last ten games at this line: green bars cleared it, red ones didn't, and the dashed mark is the line. \"7/10\" = cleared it 7 times."],
    range:['Range · games', 'The first numbers are where the true chance most likely sits (80% range); "12g" is how many games it\'s based on. Wide range or few games = less certain.'],
    value:['Value spots', "Bets where Polymarket gives at least a 30% chance and our model is 15+ points higher — the model's biggest disagreements with the market. On the graded record they're roughly break-even so far, so treat them as leads to research, not sure things."],
    clv:['Price moved its way', "Closing line value: how the Polymarket price of each graded pick moved between when the site first recorded it and the start of the game. If prices keep moving toward the model's picks, the market is coming around to what the model saw first — the most reliable early sign of a real edge, long before the win-loss record means much. If they mostly move away, the market knew something the model didn't."],
    surest:['Top 25 Surest', "The likeliest bets on the board, whatever they pay. Likely isn't certain: they still lose sometimes, and at 85–97¢ a single loss wipes out several wins."],
  };
  const helpBtn=(k,label)=>`<button type="button" class="qhelp" data-help="${k}" aria-expanded="false">${label}<span class="qi" aria-hidden="true">?</span></button>`;
  function legend(short){
    return `<details class="pslegend"><summary class="lg-lab">How to read a card</summary>${helpBtn('model','Model %')}${helpBtn('last10','Last 10')}${helpBtn('price','Price')}${helpBtn('payout','Payout')}${helpBtn('edge','Edge')}${short?'':helpBtn('range','Range')}</details>`;
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
    // A listed pick has a share page (p/<sport>/<key>.html, build_games.py) whose link preview names the pick;
    // anything else shares the board link itself.
    const key=shareKey(st), page=PAGE_SPORT && SHARE_KEYS && SHARE_KEYS.has(key);
    const url= page? `${location.origin}/p/${PAGE_SPORT}/${key}.html` : location.origin+location.pathname+'#'+pickHash(st);
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

  // ---- the fair chance: model and market blended, w = the model's weight (today.json refits it hourly) ----
  let FAIR_W=0.1;
  const fairOf=(prob, price)=> price==null? null : FAIR_W*prob+(1-FAIR_W)*price;
  function setFair(w){ if(!(w>=0 && w<=1) || w===FAIR_W) return; FAIR_W=w;
    document.querySelectorAll('.verdict').forEach(el=>{ if(el._o){ el.dataset.sig=''; verdict(el, el._o); } }); }

  // ---- the Player tab's verdict card: the model's chance against the price, in one call ----
  // VALUE uses the site's own two rules (price 30¢+, model 15+ points better); SKIP means
  // the price is above the model's chance; FAIR is everything between.
  function verdictOf(prob, price){
    const pv=Math.round(prob*100);
    if(price==null) return {k:'none', label:'No price', say:"No Polymarket or Kalshi price for this exact line right now — the model's chance stands on its own. Check the price before you bet."};
    const c=Math.round(price*100), e=Math.round((prob-price)*100), sg=v=>(v>=0?'+':'−')+Math.abs(v);
    const fv=Math.round(100*fairOf(prob, price)), fe=fv-c;
    if(price>=0.30 && prob-price>=0.15) return {k:'value', label:'Value', say:`Clears the value rules: the model says ${pv}% against a ${c}¢ price. The market usually knows more, though — blended, the fair chance is ${fv}%, an expected edge of ${sg(fe)}. A lead to check, not a lock.`};
    const an=/^(8|11|18)/.test(String(c))? 'an' : 'a';   // "an 80% chance", "a 60% chance"
    if(prob-price<=-0.03) return {k:'skip', label:'Skip', say:`At ${c}¢ you'd be paying for ${an} ${c}% chance; the model says ${pv}% and the fair chance is ${fv}%. Overpriced.`};
    if(price<0.30 && prob-price>=0.15) return {k:'fair', label:'Fair', say:`A big gap on paper (${sg(e)}), but at ${c}¢ it's a longshot — the value rules skip anything under 30¢. Fair chance ${fv}%.`};
    if(e>=15) return {k:'fair', label:'Fair', say:`Right on the value bar (${sg(e)}) but not clearly over it. Fair chance ${fv}% against ${c}¢.`};
    return {k:'fair', label:'Fair', say:`Fair chance ${fv}% against a ${c}¢ price — about what it costs. The model alone says ${pv}%.`};
  }
  // o: {prob, lo, hi, neff, side, line, statText, price, vn, live, marketLine, onShare} — or null to hide.
  // vn: which exchange the price is from ("P" Polymarket, "K" Kalshi), when known.
  function verdict(el, o){
    if(!el) return;
    if(!o || o.prob==null){ el.hidden=true; return; }       // keep the markup, so re-showing it doesn't replay the ring
    el._o=o;                                                  // repainted when the fitted fair weight arrives
    const pv=Math.round(o.prob*100), v=verdictOf(o.prob, o.price);
    const c=o.price!=null? Math.round(o.price*100) : null, e=c!=null? Math.round((o.prob-o.price)*100) : null;
    const tier=o.prob>=0.9?'hi':o.prob>=0.7?'mid':'lo';
    const fv=c!=null? Math.round(100*fairOf(o.prob, o.price)) : null;
    const sig=[pv,o.side,o.line,o.statText,c,v.k,o.live,o.marketLine,fv,o.vn].join('|');
    if(el.dataset.sig!==sig){
      el.dataset.sig=sig;
      el.className=`verdict v-${v.k} t-${tier}`;
      const stats = c!=null
        ? `<div class="vd-stats"><span><b>${c}¢</b>${o.live? '<i class="vd-live">● live price</i>' : 'price · last update'}${o.vn? ' · '+venueName(o.vn) : ''}</span>`+
          `<span><b>${(1/o.price).toFixed(2)}×</b>payout</span><span><b class="${e>=0?'pos':'neg'}">${e>=0?'+':'−'}${Math.abs(e)}</b>model edge</span>`+
          `<span class="vd-fair"><b>${fv}%</b><span>fair chance <button type="button" class="qhelp hq" data-help="fair" aria-expanded="false" aria-label="What is the fair chance?"><span class="qi" aria-hidden="true">?</span></button></span></span></div>`
        : (o.marketLine!=null? `<div class="vd-stats"><span class="vd-note">The market lists this prop at <b>${esc(o.marketLine)}</b> — set the line to ${esc(o.marketLine)} to compare.</span></div>` : '');
      const range=o.lo!=null? `${Math.round(o.lo*100)}–${Math.round(o.hi*100)}% range` : '';
      const games=o.neff? `${Math.round(o.neff)} games` : '';
      el.innerHTML=`<div class="ring" style="--p:${pv}"><b>${pv}<small>%</small></b></div>`+
        `<div class="vd-main"><div class="vd-top"><span class="vd-chip">${v.label}</span><span class="vd-cap">Model chance${range?' · '+range:''}${games?' · '+games:''}</span></div>`+
          `<div class="vd-bet"><span class="leantag ${esc(o.side)}">${esc(o.side)}</span><b>${esc(o.line)}</b><span>${esc(o.statText)}</span></div>`+
          stats+`<p class="vd-say">${esc(v.say)}</p></div>`+
        `<div class="vd-btns"><button type="button" class="btn vd-track" hidden></button><button type="button" class="btn ghost vd-share">🔗 Share</button></div>`;
    }
    const sb=el.querySelector('.vd-share'); if(sb) sb.onclick=o.onShare||null;
    const tb=el.querySelector('.vd-track');
    if(tb){ const t=o.track, label=on=>{ tb.textContent= on? '✓ Tracked' : '+ Track this bet'; tb.classList.toggle('on', !!on); };
      tb.hidden=!t; if(t){ label(t.on);
        tb.onclick=()=>{ const on=t.toggle(); t.on=on; label(on); toast(on? 'Added to My bets — find it in the Tools tab' : 'Removed from My bets'); }; } }
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
      `<div class="verdict" hidden></div>`+fastHtml(o)+reasonHtml(o)+
      (v.length>=3? `<div class="ps-l10"><div class="ps-sub">Last ${v.length} games · cleared ${esc(o.line)} <b>${hits} of ${v.length}</b></div>${bigSpark(v, o.line, o.side)}</div>` : '')+
      `<div class="ps-actions"><button type="button" class="btn ps-open">Full breakdown →</button></div>`+
      promoHtml(o)+moreHtml(o.more),
      `${o.name} ${o.side} ${o.line} ${o.statText}`);
    verdict(w.querySelector('.verdict'), o);
    w.querySelector('.ps-open').onclick=()=>{ closeSheet(); if(o.onOpen) o.onOpen(); };
    w.querySelectorAll('.ps-mi').forEach(b=>b.onclick=()=>{ const it=o.more[+b.dataset.g].items[+b.dataset.i]; closeSheet(); it.open(); });
  }
  // Where to find the pick: the exchange with the cheaper price for this pick first. Plain links, no referral codes.
  // data-place="sheet" makes the click count as "<exchange>-site-sheet" on the team dashboard.
  const REF={P:{name:'Polymarket', href:'https://polymarket.us'},
             K:{name:'Kalshi', href:'https://kalshi.com'}};
  function promoHtml(o){
    const a=REF[o.vn==='K'? 'K' : 'P'], b=REF[o.vn==='K'? 'P' : 'K'];
    return `<div class="ps-promo"><a class="ps-ref" href="${esc(a.href)}" target="_blank" rel="noopener" data-place="sheet"><span>Find this prop on <b>${a.name}</b> →</span></a>`+
      `<a class="ps-ref2" href="${esc(b.href)}" target="_blank" rel="noopener" data-place="sheet">or on ${b.name} →</a>`+
      `<p class="ps-fine">Research, not betting advice.</p></div>`;
  }
  // "More from this game" / "More for <player>": o.more = [{title, items:[{name, side, line, statText, prob, open}]}]
  function moreHtml(groups){
    return (groups||[]).map((g,gi)=> !(g.items||[]).length? '' :
      `<div class="ps-more"><div class="ps-sub">${esc(g.title)}</div>`+g.items.map((it,i)=>
        `<button type="button" class="ps-mi" data-g="${gi}" data-i="${i}"><span class="ps-mt"><b>${esc(it.name)}</b> <span class="leantag ${esc(it.side)}">${esc(it.side)}</span> ${esc(it.line)} ${esc(it.statText)}</span>`+
        `<span class="ps-mp">${Math.round(it.prob*100)}%</span></button>`).join('')+`</div>`).join('');
  }
  // Same game, then same player, from a board's modeled picks; key() tells props apart, game() names the game.
  function relatedPicks(r, pool, o){
    const seen=new Set([o.key(r)]), uniq=[];
    pool.forEach(x=>{ const k=o.key(x); if(!seen.has(k)){ seen.add(k); uniq.push(x); } });
    const item=x=>({name:x.name, side:x.side, line:x.line, statText:x.statText, prob:x.prob, open:()=>o.open(x)});
    // near-certain props (93%+) pay pennies, so they come after the rest; within each, likeliest first
    const rank=(a,b)=>((a.prob>=0.93)-(b.prob>=0.93)) || (b.prob-a.prob);
    const onePer=(rows, by)=>{ const s=new Set(); return rows.filter(x=>{ const k=by(x); if(s.has(k)) return false; s.add(k); return true; }); };
    const gk=o.game(r), pk=String(o.pid(r));
    return [{title:'More from this game', items:onePer(uniq.filter(x=>o.game(x)===gk && String(o.pid(x))!==pk).sort(rank), x=>String(o.pid(x))).slice(0,4).map(item)},
            {title:`More for ${r.name}`, items:onePer(uniq.filter(x=>String(o.pid(x))===pk).sort(rank), x=>x.statText).slice(0,3).map(item)}];
  }

  // ---- Simple / Pro: how much the sport boards show. Simple (the default) keeps who, the line, the
  // chance, the price and the last 10; Pro adds every number and the Tools tab. Saved on this device
  // only (psl_view). <html data-view> is set here, in the <head>, so a page never flashes the wrong view;
  // app.css hides .pro-only / .simple-only parts and the extra card numbers. ----
  const VIEW_KEY='psl_view';
  function getView(){ try{ return localStorage.getItem(VIEW_KEY)==='pro'? 'pro' : 'simple'; }catch(e){ return 'simple'; } }
  function canStore(){ try{ localStorage.setItem('psl_t','1'); localStorage.removeItem('psl_t'); return true; }catch(e){ return false; } }
  // asked once: a choice, or "decide later". Without storage nobody is asked (it would come back on every page).
  function viewAsked(){ try{ return !!localStorage.getItem(VIEW_KEY) || localStorage.getItem('psl_view_asked')==='1'; }catch(e){ return true; } }
  // how: "gate" (the first-visit question) or "switch" (the header toggle); counted as click/view-<v>[-switch]/<page>
  function setView(v, how){
    v= v==='pro'? 'pro' : 'simple';
    document.documentElement.dataset.view=v;
    try{ localStorage.setItem(VIEW_KEY, v); }catch(e){}
    document.querySelectorAll('.psview button').forEach(b=>b.setAttribute('aria-pressed', String(b.dataset.v===v)));
    const gc=window.goatcounter;
    if(how && gc && typeof gc.count==='function'){
      const page=(location.pathname.match(/\/(nfl|nba|nhl|mlb)\.html$/) || [])[1] || 'home', k='view-'+v+(how==='switch'? '-switch' : '');
      gc.count({path:'click/'+k+'/'+page, title:(how==='switch'? 'Switched to ' : 'Chose ')+v+' on '+page, event:true});
    }
  }
  document.documentElement.dataset.view=getView();
  // The Simple | Pro toggle, in a sport page's header (the home page shows the same in both).
  function viewSwitch(){
    const host=document.querySelector('.apptop-in'); if(!host || host.querySelector('.psview')) return;
    const v=getView(), s=document.createElement('div');
    s.className='psview'; s.setAttribute('role','group'); s.setAttribute('aria-label','How much to show');
    s.innerHTML=`<button type="button" data-v="simple" aria-pressed="${v==='simple'}" title="Today's best picks, the essentials">Simple</button>`+
      `<button type="button" data-v="pro" aria-pressed="${v==='pro'}" title="Every number, sorting and the Tools tab">Pro</button>`;
    s.onclick=e=>{ const b=e.target.closest('button'); if(b && b.getAttribute('aria-pressed')!=='true') setView(b.dataset.v, 'switch'); };
    host.insertBefore(s, host.querySelector('.appctas'));
  }
  if(document.readyState!=='loading') viewSwitch(); else document.addEventListener('DOMContentLoaded', viewSwitch);

  // ---- one-time 18+ check. It carries the storage notice, so a first visit sees one pop-up, not two.
  // Then, once, how to see the boards (Simple or Pro); a visitor who passed the check before
  // the question existed gets just the question. ----
  const GATE_LOGO='<svg class="psgate-logo" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="14" fill="#0f2038"/><path d="M32,6 Q32,32 54,32 Q32,32 32,58 Q32,32 10,32 Q32,32 32,6 Z" fill="#22d07f"/></svg>';
  function viewStep(card, done){
    try{ localStorage.setItem('psl_view_asked','1'); }catch(e){}
    card.innerHTML=GATE_LOGO+`<h2 id="psgate-h">How do you want to see picks?</h2>`+
      `<div class="psgate-views">`+
        `<button type="button" class="psgate-view" data-v="simple"><b>Simple <small>Recommended</small></b><span>Today's best picks with the four things that matter: who, the line, how likely it hits, and what it pays. Tap any pick for the full story.</span></button>`+
        `<button type="button" class="psgate-view" data-v="pro"><b>Pro</b><span>Everything: the model's edge, opening prices and moves, both exchanges' prices, sorting, the streak leaderboard and parlay tools, and the full rules for each list.</span></button>`+
      `</div>`+
      `<p class="psgate-fine">You can switch any time with the Simple | Pro buttons at the top of a sports page. <button type="button" class="psgate-later">Decide later</button></p>`;
    card.querySelectorAll('.psgate-view').forEach(b=>b.onclick=()=>{ setView(b.dataset.v, 'gate'); done(); });
    card.querySelector('.psgate-later').onclick=done;   // stays on Simple, and isn't asked again
    card.querySelector('.psgate-view').focus({preventScroll:true});
  }
  function ageGate(){
    let ok=false; try{ ok=localStorage.getItem('psl_age_ok')==='1'; }catch(e){}
    if(!document.body || (ok && viewAsked())) return;
    const g=document.createElement('div'); g.className='psgate'; g.setAttribute('role','dialog'); g.setAttribute('aria-modal','true'); g.setAttribute('aria-labelledby','psgate-h');
    g.innerHTML=`<div class="psgate-card"></div>`;
    const card=g.firstChild, close=()=>{ g.remove(); document.documentElement.classList.remove('ps-lock'); };
    document.body.appendChild(g); document.documentElement.classList.add('ps-lock');
    if(ok){ viewStep(card, close); return; }
    card.innerHTML=GATE_LOGO+
      `<h2 id="psgate-h">Are you 18 or older?</h2>`+
      `<p>Prop Streak Lab is player-prop research for adults. It isn't a sportsbook and takes no bets. Some links go to Polymarket and Kalshi, which have their own age and location rules.</p>`+
      `<div class="psgate-btns"><button type="button" class="btn" id="psgate-ok">Yes, I'm 18 or older</button><a class="btn ghost" href="https://www.google.com" rel="noopener">No, leave</a></div>`+
      `<p class="psgate-fine">We use only essential local storage for your preferences and cookieless analytics — no ads, no cross-site tracking. <a href="cookies.html">Cookie Policy</a> · <a href="privacy.html">Privacy</a><br>Gambling problem? Call 1-800-522-4700 or visit <a href="https://www.ncpgambling.org" rel="noopener" target="_blank">ncpgambling.org</a>.</p>`;
    const bar=document.getElementById('pslcookie'); if(bar) bar.hidden=true;    // the check carries the same notice
    const btn=g.querySelector('#psgate-ok'); btn.focus({preventScroll:true});
    btn.onclick=()=>{ try{ localStorage.setItem('psl_age_ok','1'); localStorage.setItem('psl_notice_ok','1'); }catch(e){}
      if(canStore() && !viewAsked()) viewStep(card, close); else close(); };
  }
  if(document.readyState!=='loading') ageGate(); else document.addEventListener('DOMContentLoaded', ageGate);

  // ---- My bets: props you tracked, graded from the box score, saved on this device only ----
  const BETS_KEY='psl_mybets';
  function loadBets(){ try{ const a=JSON.parse(localStorage.getItem(BETS_KEY)||'[]'); return Array.isArray(a)? a : []; }catch(e){ return []; } }
  // html.has-bets keeps the Tools tab (where My bets lives) in the Simple view too
  const markBets=a=>document.documentElement.classList.toggle('has-bets', a.length>0);
  function saveBets(a){ try{ localStorage.setItem(BETS_KEY, JSON.stringify(a.slice(-300))); }catch(e){} markBets(a); }
  markBets(loadBets());
  const betId=b=>[b.sport, b.pid, b.stat, b.line, b.side, b.game].join('|');
  const isTracked=b=> !!b && loadBets().some(x=>x.id===betId(b));
  // b: {sport, pid, name, team, opp, stat, statText, line, side, prob, price, game, when} — returns whether it's now tracked
  function toggleBet(b){ const a=loadBets(), id=betId(b), i=a.findIndex(x=>x.id===id);
    if(i>=0){ a.splice(i,1); saveBets(a); return false; }
    a.push(Object.assign({id, at:new Date().toISOString()}, b)); saveBets(a); return true; }
  // resultFor(b) -> {res:'hit'|'miss'|'push'|'void', actual} once graded, or null while pending
  function renderBets(el, sport, resultFor){
    if(!el) return;
    const mine=loadBets().filter(b=>b.sport===sport).reverse();
    if(!mine.length){ el.innerHTML=`<p class="mktnote">No bets tracked yet. Open a pick's details, or any prop on the Player tab, and tap <b>+ Track this bet</b> — it's graded here from the box score once the game is final. Saved on this device only.</p>`; return; }
    const LBL={hit:'Hit', miss:'Miss', push:'Push', void:"Void · didn't play", pend:'Pending'};
    let hit=0, miss=0, push=0, units=0, priced=0;
    const rows=mine.map(b=>{
      let r=null; try{ r=resultFor(b); }catch(e){}
      const res=r? r.res : 'pend';
      if(res==='hit'){ hit++; if(b.price){ priced++; units+=1/b.price-1; } }
      else if(res==='miss'){ miss++; if(b.price){ priced++; units-=1; } }
      else if(res==='push') push++;
      const px=b.price!=null? `${Math.round(b.price*100)}¢` : 'no price';
      return `<div class="betrow r-${res}"><div class="br-main"><b>${esc(b.name)}</b> <span class="leantag ${esc(b.side)}">${esc(b.side)}</span> <b>${esc(b.line)}</b> ${esc(b.statText)}`+
        `<span class="br-sub">vs ${esc(b.opp)} · ${esc(b.when||b.game)} · model ${Math.round(b.prob*100)}% · ${px}</span></div>`+
        `<span class="br-res">${LBL[res]}${r && r.actual!=null? ` · ${esc(num(r.actual))}` : ''}</span>`+
        `<button type="button" class="br-x" data-id="${esc(b.id)}" aria-label="Remove this bet">✕</button></div>`;
    });
    if(!welcomed[sport]){ welcomed[sport]=true; welcomeBack(sport, mine.map(b=>{ let r=null; try{ r=resultFor(b); }catch(e){} return {b, res: r? r.res : 'pend'}; })); }
    const n=hit+miss;
    el.innerHTML=`<div class="betsum"><span><b>${hit}–${miss}${push? '–'+push : ''}</b> record</span>`+
      (n? `<span><b>${Math.round(100*hit/n)}%</b> hit</span>` : '')+
      (priced? `<span><b class="${units>=0?'pos':'neg'}">${units>=0?'+':'−'}${Math.abs(units).toFixed(2)}u</b> at your tracked prices</span>` : '')+
      `<span><b>${mine.length}</b> tracked</span></div>`+rows.join('');
    el.querySelectorAll('.br-x').forEach(x=>x.onclick=()=>{ saveBets(loadBets().filter(b=>b.id!==x.dataset.id)); renderBets(el, sport, resultFor); });
  }

  // which sport board this is (null on the home page and the other pages)
  const PAGE_SPORT=(location.pathname.match(/\/(nfl|nba|nhl|mlb)\.html$/)||[])[1]||null;
  const SPORT_LBL={nfl:'NFL', nba:'NBA', nhl:'NHL', mlb:'MLB'};

  // share pages that exist for this board's picks (p/keys.json, build_games.py): {sport: {key: expiry}}
  let SHARE_KEYS=null;
  const shareKey=st=> `${st.player.id}-${st.stat}-${String(Number(st.line))}-${st.ou}`;   // = build_games.share_key
  if(PAGE_SPORT) fetch('p/keys.json',{cache:'no-store'}).then(r=>r.ok? r.json() : null)
    .then(d=>{ SHARE_KEYS=new Set(Object.keys((d&&d[PAGE_SPORT])||{})); }).catch(()=>{});
  // props whose price moved 10c+ in the last hour (today.json "fast", build_today.fast_moves): a warning in the pick sheet
  let FAST=[];
  if(PAGE_SPORT) fetch('today.json',{cache:'no-store'}).then(r=>r.ok? r.json() : null)
    .then(d=>{ FAST=((d&&d.fast)||[]).filter(f=>f.sport===PAGE_SPORT); }).catch(()=>{});
  // Plain-English reasons for a pick, from its own numbers: the last games against the line, the
  // streak, the average against the line, and the model against the market price.
  function reasonHtml(o){
    const v=(o.vals||[]).filter(x=>x!=null && isFinite(x)).slice(-10), line=+o.line, under=o.side==='under';
    if(v.length<3 || !isFinite(line)) return '';
    const clears=x=> under? x<line : x>line, hits=v.filter(clears).length;
    let streak=0; for(let i=v.length-1;i>=0 && clears(v[i]);i--) streak++;
    const avg=v.reduce((a,b)=>a+b,0)/v.length, fmt=x=>Number.isInteger(x)? String(x) : x.toFixed(1);
    const out=[`Cleared ${esc(o.line)} in <b>${hits} of the last ${v.length}</b> games${streak>=3? `, including <b>${streak} straight</b>` : ''}.`];
    const gap=under? line-avg : avg-line;
    out.push(`Averages <b>${fmt(avg)}</b> over those games, ${gap>=0? `${fmt(Math.abs(gap))} ${under?'under':'over'} the line` : `${fmt(Math.abs(gap))} on the wrong side of the line`}.`);
    if(o.prob!=null && o.price!=null && isFinite(o.price)){
      const p=Math.round(o.prob*100), c=Math.round(o.price*100), d=p-c;
      out.push(d>=3? `The model gives it <b>${p}%</b> and the market price is <b>${c}¢</b>: the model rates it ${d} points higher.`
             : d<=-3? `The model gives it <b>${p}%</b> but the market price is <b>${c}¢</b>: the market rates it higher, so the payout is thin.`
             : `The model gives it <b>${p}%</b>, about the same as the market price (${c}¢).`);
    }
    if(o.neff!=null && isFinite(o.neff)) out.push(`Based on about <b>${Math.round(o.neff)}</b> games of history, weighted to the most recent.`);
    return `<div class="ps-why"><b>Why</b><ul>${out.map(x=>`<li>${x}</li>`).join('')}</ul></div>`;
  }
  function fastHtml(o){
    const f=FAST.find(x=>x.player===o.name && +x.line===+o.line && x.side===o.side);
    return f? `<div class="ps-fast"><b>Market moving fast:</b> ${Math.round(f.was*100)}¢ → ${Math.round(f.price*100)}¢ in the last hour. That's often injury or lineup news, so check it before you bet.</div>` : '';
  }

  // ---- a small card at the bottom of the screen (welcome back, home-screen tip); one at a time ----
  // actions: [{label, href?, tab?, primary?, run?}] — tab clicks that board tab instead of following the link
  function note(html, actions, onClose){
    if(document.getElementById('psnote')) return null;
    const w=document.createElement('div'); w.id='psnote'; w.className='psnote'; w.setAttribute('role','status');
    w.innerHTML=`<button type="button" class="psn-x" aria-label="Close">✕</button><p>${html}</p>`+
      (actions&&actions.length? `<div class="psn-acts">${actions.map((a,i)=> a.href? `<a class="psn-b${a.primary?' go':''}" href="${esc(a.href)}" data-i="${i}">${esc(a.label)}</a>` : `<button type="button" class="psn-b${a.primary?' go':''}" data-i="${i}">${esc(a.label)}</button>`).join('')}</div>` : '');
    const close=()=>{ w.remove(); if(onClose) onClose(); };
    w.querySelector('.psn-x').onclick=close;
    w.querySelectorAll('[data-i]').forEach(b=>b.onclick=e=>{ const a=actions[+b.dataset.i];
      if(a.tab){ const t=document.querySelector(`.tab[data-tab="${a.tab}"]`); if(t){ e.preventDefault(); t.click(); } }
      if(a.run){ e.preventDefault(); a.run(); }
      close(); });
    document.body.appendChild(w);
    return w;
  }
  const quiet=()=> document.documentElement.classList.contains('ps-lock') || !!document.getElementById('psnote');

  // ---- welcome back: tracked bets graded since this visitor last opened this board ----
  // Remembers each bet's last-seen result on this device; anything newly graded gets one summary.
  const SEEN_KEY='psl_bets_seen', welcomed={};
  function welcomeBack(sport, rows){
    let seen={}; try{ seen=JSON.parse(localStorage.getItem(SEEN_KEY)||'{}')||{}; }catch(e){}
    const recent=Date.now()-14*864e5;
    const fresh=rows.filter(x=>x.res!=='pend' && seen[x.b.id]!==x.res && Date.parse(x.b.at||0)>recent);
    rows.forEach(x=>{ if(x.res!=='pend') seen[x.b.id]=x.res; });
    try{ localStorage.setItem(SEEN_KEY, JSON.stringify(seen)); }catch(e){}
    if(!fresh.length) return;
    const c=k=>fresh.filter(x=>x.res===k).length, hit=c('hit'), miss=c('miss');
    const bits=[hit? `<b>${hit} hit</b>` : '', miss? `${miss} missed` : '', c('push')? `${c('push')} pushed` : '', c('void')? `${c('void')} void` : ''].filter(Boolean).join(', ');
    const go=()=>note(`<b>Welcome back.</b> ${fresh.length===1? 'One of your tracked bets was' : fresh.length+' of your tracked bets were'} graded since your last visit: ${bits}.`,
      [{label:'See My bets', href:'#tools', tab:'tools', primary:true}]);
    setTimeout(()=>{ if(!quiet()) go(); else setTimeout(()=>{ if(!quiet()) go(); }, 8000); }, 1200);
  }
  // Home page: remind a returning visitor what they're tracking, once per visit, with a link to each board.
  function homeBets(){
    if(PAGE_SPORT || !/\/(index\.html)?$/.test(location.pathname)) return;
    try{ if(sessionStorage.getItem('psl_home_bets')) return; sessionStorage.setItem('psl_home_bets','1'); }catch(e){}
    const mine=loadBets(); if(!mine.length) return;
    const today=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York'}).format(new Date());
    const by={}; mine.forEach(b=>{ by[b.sport]=(by[b.sport]||0)+1; });
    const done=mine.filter(b=> /^\d{4}-\d{2}-\d{2}$/.test(b.game||'')? b.game<today : Date.now()-Date.parse(b.at||0)>4*864e5).length;
    const sports=Object.keys(by).sort((a,b)=>by[b]-by[a]);
    const list=sports.map(s=>`${SPORT_LBL[s]||s} ${by[s]}`).join(' · ');
    setTimeout(()=>{ if(quiet()) return;
      note(`You're tracking <b>${mine.length} bet${mine.length===1?'':'s'}</b> (${esc(list)}).${done? ` ${done===1? 'One game has' : done+' games have'} finished: see how they did.` : ''}`,
        sports.slice(0,2).map((s,i)=>({label:`${SPORT_LBL[s]||s} bets`, href:`./${s}.html#tools`, primary:i===0}))); }, 1500);
  }

  // ---- home-screen tip: phones only, for returning visitors, at most twice, never once dismissed ----
  // Also counts opens from the home screen (one anonymous GoatCounter event per visit).
  let installEvt=null;
  addEventListener('beforeinstallprompt', e=>{ e.preventDefault(); installEvt=e; });
  function homeScreen(){
    const ua=navigator.userAgent||'', standalone=(window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone===true;
    const ss=k=>{ try{ return sessionStorage.getItem(k); }catch(e){ return '1'; } }, ssSet=k=>{ try{ sessionStorage.setItem(k,'1'); }catch(e){} };
    if(standalone){
      if(!ss('psl_app_open')){ ssSet('psl_app_open'); setTimeout(()=>{ const gc=window.goatcounter; if(gc && typeof gc.count==='function')
        gc.count({path:'click/home-screen-open/'+(PAGE_SPORT||'home'), title:'Opened from the home screen', event:true}); }, 3000); }
      return;
    }
    if(!/iPhone|iPad|iPod|Android/i.test(ua)) return;
    let st={visits:0, shown:0, off:false}; try{ st=Object.assign(st, JSON.parse(localStorage.getItem('psl_a2hs')||'{}')); }catch(e){}
    if(!ss('psl_a2hs_v')){ ssSet('psl_a2hs_v'); st.visits++; }
    const save=()=>{ try{ localStorage.setItem('psl_a2hs', JSON.stringify(st)); }catch(e){} }; save();
    if(st.off || st.shown>=2 || st.visits<2 || ss('psl_a2hs_s')) return;
    const inApp=/Instagram|FBAN|FBAV|Snapchat|TikTok|musical_ly|Line\//i.test(ua), ios=/iPhone|iPad|iPod/i.test(ua);
    setTimeout(()=>{ if(quiet()) return;
      let html, acts=[{label:'Got it', run:()=>{ st.off=true; save(); }}];
      if(inApp) html=`<b>Coming back often?</b> Open this page in ${ios? 'Safari' : 'Chrome'} and add it to your Home Screen. Prop Streak Lab then opens with one tap, like an app.`;
      else if(ios) html=`<b>Add Prop Streak Lab to your Home Screen.</b> Tap the <b>three lines</b> in the bottom right, then <b>Share</b>, then <b>View More</b>, then <b>Add to Home Screen</b>. It opens with one tap, like an app.`;
      else if(installEvt){ html=`<b>Add Prop Streak Lab to your Home Screen</b> so it opens with one tap, like an app.`;
        acts=[{label:'Add to Home Screen', primary:true, run:()=>{ st.off=true; save(); installEvt.prompt(); }}, {label:'Not now'}]; }
      else html=`<b>Add Prop Streak Lab to your Home Screen.</b> Tap the menu (⋮), then <b>Add to Home screen</b>. It opens with one tap, like an app.`;
      if(note(html, acts)){ st.shown++; save(); ssSet('psl_a2hs_s'); }
    }, 25000);
  }
  function engage(){ homeBets(); homeScreen(); }
  if(document.readyState!=='loading') engage(); else document.addEventListener('DOMContentLoaded', engage);

  // ---- trust line under each hero: when the data last updated, and how many picks are graded in public ----
  // Both come from today.json, which the hourly job rewrites on every run.
  function ago(ms){ const m=Math.max(0, Math.round((Date.now()-ms)/60000));
    if(m<1) return 'just now'; if(m<60) return m+' min ago'; const h=Math.round(m/60); return h<48? h+(h===1?' hour':' hours')+' ago' : Math.round(h/24)+' days ago'; }
  // The latest graded day's results (today.json "last", from build_today.py): on a sport board,
  // that sport's Top 25 and Value record for the day; on the home page, each sport's Top 25 line.
  const dayLbl=d=>new Date(d+'T12:00:00Z').toLocaleDateString('en-US',{weekday:'short', month:'short', day:'numeric', timeZone:'UTC'});
  function lastResults(t){
    const L=(t && t.last)||{};
    if(PAGE_SPORT){
      const r=L[PAGE_SPORT]; if(!r) return '';
      const parts=[];
      if(r.T) parts.push(`Top 25 Surest <b>${r.T.hit}/${r.T.n} hit</b>`);
      if(r.V) parts.push(`Value <b>${r.V.hit}/${r.V.n}</b>${r.V.units!=null? ` (${r.V.units>=0?'+':'−'}${Math.abs(r.V.units).toFixed(1)}u)` : ''}`);
      return `<span class="tr-res">${icon('circle-check')}Last results, ${esc(dayLbl(r.day))}: ${parts.join(' · ')} <a href="#past" data-tab-go="past">See every pick →</a></span>`;
    }
    const recent=new Date(Date.now()-3*864e5).toISOString().slice(0,10);
    const parts=Object.keys(SPORT_LBL).filter(s=>L[s] && L[s].T && L[s].day>=recent)
      .map(s=>`<a href="./${s}.html#past">${SPORT_LBL[s]} <b>${L[s].T.hit}/${L[s].T.n}</b></a>`);
    return parts.length? `<span class="tr-res">${icon('circle-check')}Latest Top 25 results: ${parts.join(' · ')}</span>` : '';
  }
  function trust(){
    const el=document.getElementById('pstrust'); if(!el) return;
    const paint=t=>{
      let upd=t && Date.parse(t.gen);
      if(!isFinite(upd)){ const lm=Date.parse(document.lastModified); upd= isFinite(lm) && lm<=Date.now()+6e4 && Date.now()-lm<30*864e5? lm : null; }
      const tr=t && t.tracked, since=tr && tr.since? new Date(tr.since+'T12:00:00Z').toLocaleDateString('en-US',{month:'short', day:'numeric', year:'numeric'}) : '';
      el.innerHTML=(upd? `<span class="tr-upd"><i class="tr-dot" aria-hidden="true"></i>Updated <b data-ago="${upd}">${ago(upd)}</b></span>` : '')+
        (tr && tr.graded? `<span class="tr-grd">${icon('shield-check')}<b>${tr.graded.toLocaleString('en-US')} picks graded in public</b>${since? ' since '+esc(since) : ''}</span>` : '')+
        lastResults(t)+
        `<a class="tr-how" href="methodology.html">How the model works →</a>`;
      el.hidden=false;
      const go=el.querySelector('[data-tab-go]');
      if(go) go.onclick=e=>{ const tab=document.querySelector(`.tab[data-tab="${go.dataset.tabGo}"]`); if(tab){ e.preventDefault(); tab.click(); } };
    };
    paint(null);
    fetch('today.json',{cache:'no-store'}).then(r=>r.ok? r.json() : null).then(t=>{ if(t){ paint(t); if(t.fair) setFair(t.fair.w); } }).catch(()=>{});
    setInterval(()=>el.querySelectorAll('[data-ago]').forEach(b=>{ b.textContent=ago(+b.dataset.ago); }), 60000);
  }
  if(document.readyState!=='loading') trust(); else document.addEventListener('DOMContentLoaded', trust);

  // ---- "New here?": a key to the board, above its tabs, until the visitor closes it: one line in
  // Simple, the four-line key in Pro ----
  function newHere(){
    const tabs=document.querySelector('.tabs[role="tablist"]'); if(!tabs || document.getElementById('psnew')) return;
    let seen=false; try{ seen=localStorage.getItem('psl_newhere_ok')==='1'; }catch(e){}
    if(seen) return;
    const box=document.createElement('section'); box.id='psnew'; box.className='psnew'; box.setAttribute('aria-label','How to read this page');
    box.innerHTML='<p class="psnew-line simple-only"><span><b>72%</b> = our chance it hits · <b>57¢</b> = the price, so it pays 1.75× · Tap a pick for the full story. Research, not advice. 18+.</span>'+
      '<button type="button" class="psnew-x" aria-label="Close">Got it</button></p>'+
      '<div class="pro-only"><div class="psnew-h"><b>New here? How to read a pick</b><button type="button" class="psnew-x" aria-label="Close">Got it</button></div>'+
      '<ul>'+
      '<li><b class="k">72%</b> Our model’s chance the pick hits, from the player’s game log and the matchup.</li>'+
      '<li><b class="k">57¢</b> What Polymarket or Kalshi charges for a $1 payout, so it pays <b>1.75×</b>. A low price means a bigger payout but a less likely pick.</li>'+
      '<li><b class="k">⚡ Value spots</b> Our chance is well above the price: bigger payouts, more misses.</li>'+
      '<li><b class="k">🔒 Top 25 Surest</b> The picks most likely to hit, with small payouts.</li>'+
      '</ul><p class="psnew-f">Every pick is recorded before the game and graded afterward, wins and losses, in <b>Past picks</b>. Research, not advice. 18+.</p></div>';
    tabs.parentNode.insertBefore(box, tabs);
    box.querySelectorAll('.psnew-x').forEach(b=>b.onclick=()=>{ box.remove(); try{ localStorage.setItem('psl_newhere_ok','1'); }catch(e){} });
  }
  if(document.readyState!=='loading') newHere(); else document.addEventListener('DOMContentLoaded', newHere);

  // ---- sport-page layout: the email button below the lists, and a tab bar that stays under the
  // header and brings its tab's content into view when tapped ----
  function boardLayout(){
    const tabs=document.querySelector('.app .tabs[role="tablist"]'), top=document.querySelector('.apptop'); if(!tabs) return;
    const promo=document.querySelector('.wrap.app > .promo'); if(promo) promo.parentNode.appendChild(promo);
    const fit=()=>{ if(top) document.documentElement.style.setProperty('--ps-toph', top.offsetHeight+'px'); };
    fit(); addEventListener('resize', fit);
    const mark=document.createElement('div'); mark.className='tabs-mark'; tabs.parentNode.insertBefore(mark, tabs);
    tabs.addEventListener('click', e=>{
      if(!e.target.closest('.tab')) return;
      setTimeout(()=>{   // after the page's own handler, which jumps to the top
        const y=mark.getBoundingClientRect().top+scrollY-(top? top.offsetHeight : 0);
        if(Math.abs(scrollY-y)>4) scrollTo(0, y);
      }, 0);
    });
  }
  if(document.readyState!=='loading') boardLayout(); else document.addEventListener('DOMContentLoaded', boardLayout);

  // ---- opening vs current price: has the market moved toward a pick since it was recorded? ----
  // open/now are fractions for the side taken. Up = the price rose since the site first
  // recorded the pick, i.e. the market moved toward it (closing line value). closed=true
  // is the Past picks form: the price at recording -> the last one before the game.
  function pxMove(open, now, closed){
    if(open==null || now==null) return '';
    const o=Math.round(open*100), n=Math.round(now*100), d=n-o;
    if(!closed && !d) return '';          // a card only mentions the opening price once it has moved
    const cls=d>=1?'up':d<=-1?'dn':'flat', arrow=d>=1?'\u25b2'+d:d<=-1?'\u25bc'+(-d):'\u00b10';
    const say=d>=1? `the market moved ${d}\u00a2 toward this pick` : d<=-1? `the market moved ${-d}\u00a2 away from this pick` : 'no real move';
    const title=`Price (the cheaper of Polymarket and Kalshi) when the site first recorded this pick: ${o}\u00a2. ${closed?'Last price before it locked (or, for picks before October 7, 2026, before the game)':'Now'}: ${n}\u00a2 \u2014 ${say}.`;
    return `<span class="pxmove ${cls}${closed?' inl':''}" title="${esc(title)}">${closed? `${o}\u00a2 \u2192 ${n}\u00a2` : `opened ${o}\u00a2`} <b>${arrow}</b></span>`;
  }

  // ---- nothing is certain: no chance above 99% (or below 1%) is shown, even on picks recorded before
  // the builders capped it (P_MAX in each model) ----
  const P_MAX=0.99;
  function cap(p){ return p==null? p : Math.min(P_MAX, Math.max(1-P_MAX, +p)); }
  function capPick(o){ if(o) ['prob','lo','hi'].forEach(k=>{ if(o[k]!=null) o[k]=cap(o[k]); }); return o; }

  // ---- ruled out for a thin market: a pick that would have made Value (or Top 25 Surest, where that
  // needs a price) but had under $25 offered near its price on both exchanges (depth.py "th").
  // It was never recommended, so Past picks leaves it out. opt: {cents: 100 for NFL prices,
  // tMin: the Top 25 chance floor where Top 25 needs a price (MLB, NHL)} ----
  // Also left out: a Top 25 / Value pick from the rule's launch day (Oct 7, 2026) recorded before the
  // rule ran — its depth was never checked (the site owner's call; depth.unchecked in the builders);
  // and one that would have qualified but was waiting on injury news (holds.py "hd") when its game began.
  const RULE_DAY='2026-10-07';
  function thinOut(p, opt){
    if(p && p.lists && String(p.date)===RULE_DAY && p.vn==null && !p.th) return true;
    if(!p || !(p.th || p.hd) || p.lists || p.price==null || p.prob==null) return false;   // on a list = it was recommended
    const o=opt||{}, px=p.price/(o.cents||1), q=+p.prob;
    const value=(p.neff==null || p.neff>=6) && px>=0.30 && q-px>=0.15;
    return value || (o.tMin!=null && q>=o.tMin);
  }

  // ---- Polymarket and Kalshi side by side (kalshi.py) ----
  // pp/kp: what you'd pay for the pick's side on each exchange, as fractions (null = that
  // exchange doesn't list this exact prop at this line). vn: the one the pick is judged on —
  // the cheaper — "P" or "K". Picks recorded before Kalshi was added have only a Polymarket price.
  function venueName(vn){ return vn==='K'? 'Kalshi' : 'Polymarket'; }
  // thinP/thinK: under $25 is offered within 2\u00a2 of that price (depth.py), so a bet would move it.
  function venues(pp, kp, vn, thinP, thinK){
    if(pp==null && kp==null) return '';
    const one=(name, v, on, thin)=>`<span class="vq${on?' best':''}${thin && v!=null?' thin':''}">${name} <b>${v==null? '\u2014' : Math.round(v*100)+'\u00a2'}</b>${thin && v!=null? ' <i>thin</i>' : ''}</span>`;
    const title=`What you'd pay for this side on each exchange (\u2014 = not listed at this line). The highlighted one is the price the edge, Top 25 Surest and Value use: the cheaper exchange with $25+ offered within 2\u00a2 of its price. \u201cthin\u201d = less than that is offered, so a bet would move the price.`;
    return `<span class="venues" title="${esc(title)}">${one('Polymarket', pp, vn!=='K' && pp!=null, thinP)}${one('Kalshi', kp, vn==='K', thinK)}</span>`;
  }

  // ---- locked picks: the builders lock a pick when its game starts within 30 minutes (lock_picks) ----
  // From then on its spot on the lists, its chance and its price stay as published.
  function lockNote(){
    return `<p class="mktnote locknote"><span class="lockbadge">\ud83d\udd12 Locked</span><span>The game starts within 30 minutes, so the pick is final: its Top 25 / Value status, its chance and its price won\u2019t change again. The site updates about every 10 minutes, so picks lock at least 10 minutes before the start.</span></p>`;
  }
  // A strip across the top of a locked pick's card, so a final pick reads as final at a glance.
  function lockRibbon(lk){
    const t=Date.parse(lk), at=isFinite(t)? ' at '+new Date(t).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'}) : '';
    return `<div class="lockribbon" title="${esc(`Locked${at}: the game starts within 30 minutes, so this pick is final.`)}"><b>🔒 Locked</b><span>Final pick · won’t change</span></div>`;
  }
  function lockBadge(lk){
    const t=Date.parse(lk), at=isFinite(t)? ' at '+new Date(t).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'}) : '';
    return `<span class="lockbadge" title="${esc(`Locked${at}: the game starts within 30 minutes, so this pick is final \u2014 its Top 25 / Value status, its chance and its price won\u2019t change again.`)}">\ud83d\udd12 Locked</span>`;
  }

  return {teamVars, ticker, until, skeleton, esc, hashFor, pickHash, parsePickHash, syncHash, sharePick, toast, helpBtn, spark, verdict, icon, sheet, closeSheet, pickSheet, relatedPicks,
          isTracked, toggleBet, renderBets, loadBets, fairOf, setFair, pxMove, lockBadge, lockRibbon, lockNote, venues, venueName, cap, capPick, thinOut, getView, setView};
})();

// ---- live tracker: follows picks through today's games from ESPN's public box scores ----
// PSLive.track(items, onUpdate): items are picks or tracked bets ({sport, player|name, team, stat,
// line, side}); onUpdate gets each with {state: 'pre'|'in'|'post'|'none', v (the stat so far),
// clock, status: 'hit'|'lost'|'push'|'live'|'nostat'|'pre'}. Polls every minute while a game
// is on and the page is visible. Stats it can't read from a box score are left as 'nostat'.
window.PSLive=(function(){
  const PATH={nfl:'football/nfl', nba:'basketball/nba', nhl:'hockey/nhl', mlb:'baseball/mlb'};
  const ALIAS={nfl:{LA:'LAR', WAS:'WSH'}, nhl:{UTA:'UTAH'}, mlb:{AZ:'ARI', CWS:'CHW'}, nba:{}};   // site code -> ESPN code
  const HOST='https://site.api.espn.com/apis/site/v2/sports/';
  const MLB_PITCH=new Set(['k','outs','ha','er','pbb']);
  const norm=n=>String(n||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase()
    .replace(/\b(jr|sr|ii|iii|iv)\b\.?/g,'').replace(/[^a-z ]/g,' ').replace(/\s+/g,' ').trim();
  const etDay=()=>new Date().toLocaleDateString('en-CA',{timeZone:'America/New_York'}).replace(/-/g,'');
  const num=x=>{ const v=parseFloat(x); return isFinite(v)? v : 0; };
  const part=(x,i)=>num(String(x||'').split(/[\/-]/)[i]);
  const get=u=>fetch(u,{cache:'no-store'}).then(r=>r.ok? r.json() : null).catch(()=>null);
  function codes(sport, t){ const a=ALIAS[sport]||{}, s=new Set([t]); if(a[t]) s.add(a[t]); return s; }
  // box score -> {players: {normalized name: {category: {key: value}}}, details: {doubles|triples|stolenBases: {name: n}}}
  function parseBox(sum){
    const players={}, details={};
    for(const team of (sum.boxscore && sum.boxscore.players) || []){
      for(const cat of team.statistics || []){
        const keys=cat.keys || [];
        const name=cat.name || (keys.includes('fullInnings.partInnings')? 'pitching' : keys.includes('atBats')? 'batting' : 'stats');
        for(const a of cat.athletes || []){
          const ath=a.athlete || {}, rec={};
          keys.forEach((k,i)=>{ rec[k]=(a.stats||[])[i]; });
          for(const nm of new Set([norm(ath.displayName), norm(ath.shortName)])){
            if(!nm) continue;
            (players[nm]=players[nm] || {})[name]=rec;
          }
        }
      }
    }
    // MLB: doubles, triples and steals are only in the game notes, e.g. "Pages (1, Gausman); E. Hernández 2 (5, ...)"
    for(const team of (sum.boxscore && sum.boxscore.teams) || []){
      for(const grp of team.details || []){
        for(const st of grp.stats || []){
          if(!/^(doubles|triples|stolenBases)$/.test(st.name)) continue;
          const m=details[st.name]=details[st.name] || {};
          for(const ent of String(st.displayValue||'').split(';')){
            const mm=ent.trim().match(/^(.+?)(?:\s+(\d+))?\s*\(/) || ent.trim().match(/^(.+?)(?:\s+(\d+))?$/);
            if(mm) m[norm(mm[1])]=(m[norm(mm[1])]||0)+(mm[2]? +mm[2] : 1);
          }
        }
      }
    }
    return {players, details};
  }
  function findPlayer(box, name){
    const n=norm(name), w=n.split(' '), last=w[w.length-1], init=(w[0]||'')[0];
    if(box.players[n]) return box.players[n];
    const k=Object.keys(box.players).find(x=>{ const v=x.split(' '); return v[v.length-1]===last && (v[0]||'')[0]===init; });
    return k? box.players[k] : null;
  }
  function noteCount(box, kind, name){
    const m=box.details[kind] || {}, n=norm(name), w=n.split(' '), last=w[w.length-1];
    return m[n] || m[(w[0]||'')[0]+' '+last] || m[last] || 0;
  }
  // the stat so far, or null when the box score doesn't carry it
  function statValue(sport, stat, p, box, name){
    if(!p) return null;
    if(sport==='nfl'){
      const P=p.passing||{}, R=p.rushing||{}, C=p.receiving||{};
      return {pass_yds:num(P.passingYards), pass_td:num(P.passingTouchdowns), pass_cmp:part(P['completions/passingAttempts'],0),
        pass_att:part(P['completions/passingAttempts'],1), pass_int:num(P.interceptions), rush_yds:num(R.rushingYards), rush_att:num(R.rushingAttempts),
        rec:num(C.receptions), rec_yds:num(C.receivingYards)}[stat] ?? null;
    }
    if(sport==='nba'){
      const s=Object.values(p)[0]||{}, pts=num(s.points), reb=num(s.rebounds), ast=num(s.assists);
      return {pts, reb, ast, tpm:part(s['threePointFieldGoalsMade-threePointFieldGoalsAttempted'],0), stl:num(s.steals), blk:num(s.blocks),
        to:num(s.turnovers), pra:pts+reb+ast, pr:pts+reb, pa:pts+ast, ra:reb+ast}[stat] ?? null;
    }
    if(sport==='nhl'){
      const s=p.forwards||p.defenses||p.skaters||null; if(!s) return null;
      return {g:num(s.goals), a:num(s.assists), pts:num(s.goals)+num(s.assists), sog:num(s.shotsTotal)}[stat] ?? null;
    }
    if(sport==='mlb'){
      if(MLB_PITCH.has(stat)){
        const s=p.pitching; if(!s) return null;
        const ip=String(s['fullInnings.partInnings']||'0').split('.');
        return {k:num(s.strikeouts), outs:num(ip[0])*3+num(ip[1]), ha:num(s.hits), er:num(s.earnedRuns), pbb:num(s.walks)}[stat] ?? null;
      }
      const s=p.batting; if(!s) return null;
      const h=num(s.hits), hr=num(s.homeRuns), d2=noteCount(box,'doubles',name), d3=noteCount(box,'triples',name);
      return {h, hr, rbi:num(s.RBIs), r:num(s.runs), hrr:h+num(s.runs)+num(s.RBIs), tb:h+d2+2*d3+3*hr, sb:noteCount(box,'stolenBases',name)}[stat] ?? null;
    }
    return null;
  }
  function judge(it, v, state){
    if(state==='pre') return 'pre';
    if(v==null) return 'nostat';
    const line=+it.line, done=state==='post';
    if(it.side==='under'){ if(v>line) return 'lost'; if(done) return v<line? 'hit' : 'push'; return 'live'; }
    if(v>line) return 'hit'; if(done) return v<line? 'lost' : 'push'; return 'live';
  }
  let timer=null;
  function track(items, onUpdate){
    clearTimeout(timer);
    async function poll(){
      const sports=[...new Set(items.map(i=>i.sport))].filter(s=>PATH[s]);
      const boards={}, sums={};
      await Promise.all(sports.map(async s=>{ boards[s]=await get(`${HOST}${PATH[s]}/scoreboard?dates=${etDay()}`); }));
      const out=[];
      for(const it of items){
        const sb=boards[it.sport], cs=codes(it.sport, it.team);
        const ev=sb && (sb.events||[]).find(e=>(((e.competitions||[])[0]||{}).competitors||[]).some(c=>cs.has((c.team||{}).abbreviation)));
        if(!ev){ out.push(Object.assign({}, it, {state:'none', status:'none'})); continue; }
        const st=ev.status.type, state=st.state, clock=st.shortDetail;
        if(state==='pre'){ out.push(Object.assign({}, it, {state, clock, status:'pre', v:null})); continue; }
        const key=it.sport+ev.id;
        if(!(key in sums)) sums[key]=get(`${HOST}${PATH[it.sport]}/summary?event=${ev.id}`).then(s=>s? parseBox(s) : null);
        const box=await sums[key], name=it.player||it.name;
        const v=box? statValue(it.sport, it.stat, findPlayer(box, name), box, name) : null;
        out.push(Object.assign({}, it, {state, clock, v, status:judge(it, v, state)}));
      }
      onUpdate(out);
      const live=out.some(o=>o.state==='in'), later=out.some(o=>o.state==='pre');
      if(live || later) timer=setTimeout(function again(){ if(document.hidden){ timer=setTimeout(again, 15000); return; } poll(); }, live? 60000 : 300000);
    }
    poll();
  }
  return {track, statValue, judge, parseBox, findPlayer, norm};
})();

// ---- time on page: one anonymous GoatCounter event per page view, e.g. "time/1-3m" ----
// Counts only the time the page is on screen, and sends the range the first time the visitor
// switches away or leaves. No ID or cookie, just the range; team_stats.py reads these for the
// team dashboard and keeps them out of the visit counts. Ranges must match TIME_RANGES there.
(function(){
  const RANGES = [[10,'0-10s'],[30,'10-30s'],[60,'30s-1m'],[180,'1-3m'],[600,'3-10m'],[Infinity,'10m+']];
  let since = document.visibilityState === 'visible' ? Date.now() : 0, onScreen = 0, sent = false;
  function send(){
    if (since) { onScreen += Date.now() - since; since = 0; }
    const gc = window.goatcounter;
    if (sent || !onScreen || !gc || typeof gc.count !== 'function') return;  // never shown, or GoatCounter blocked
    sent = true;
    const label = RANGES.find(r => onScreen / 1000 < r[0])[1];
    gc.count({path: 'time/' + label, title: 'Time on page: ' + label, event: true});
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') send();
    else if (!sent) since = Date.now();
  });
  addEventListener('pagehide', send);
})();

// ---- affiliate links: "?ref=<code>" (the team dashboard makes them; the affiliate agreement sets the pay). Every arrival
// through one sends "ref/<code>/visit". A browser that has never been here before also sends
// "ref/<code>/new" once the site has been on its screen for 20 seconds, counted across this visit's
// pages and paused while hidden; affiliates are paid per "new". Only the code is sent: no ID, no
// cookie. team_stats.py reads these (REF_RE). Runs before the block below, which marks the browser
// as seen (psl_views, psl_first).
(function(){
  const NEED = 20000, KEY = 'psl_ref';
  function count(path, title){
    let tries = 0;
    (function send(){
      const gc = window.goatcounter;
      if (gc && typeof gc.count === 'function') gc.count({path, title, event: true});
      else if (++tries < 40) setTimeout(send, 250);   // count.js loads async; give up after 10 s (blocked)
    })();
  }
  function save(){ try { sessionStorage.setItem(KEY, JSON.stringify(st)); } catch(e) {} }
  let st = null;
  try { st = JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch(e) {}
  let code = '';
  try { code = (new URLSearchParams(location.search).get('ref') || '').trim().toLowerCase(); } catch(e) {}
  if (/^[a-z0-9-]{2,24}$/.test(code)) {
    count('ref/' + code + '/visit', 'Affiliate visit: ' + code);
    let seen = true;   // storage blocked: can't tell new from returning, so not counted as new
    try { seen = !!(localStorage.getItem('psl_views') || localStorage.getItem('psl_first')); } catch(e) {}
    if (!seen && !st) { st = {c: code, ms: 0}; save(); }
  }
  if (!st || st.done || !/^[a-z0-9-]{2,24}$/.test(st.c || '')) return;
  let since = 0, timer = 0;
  function start(){ if (since) return; since = Date.now(); timer = setTimeout(done, Math.max(0, NEED - st.ms)); }
  function stop(){ if (!since) return; st.ms += Date.now() - since; since = 0; clearTimeout(timer); save(); }
  function done(){
    stop(); if (st.done) return;
    st.done = true; save();
    count('ref/' + st.c + '/new', 'New viewer from affiliate ' + st.c);
  }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') stop(); else if (!st.done) start(); });
  addEventListener('pagehide', stop);
  if (document.visibilityState === 'visible') start();
})();

// ---- page views and unique visitors: one anonymous GoatCounter event per page load, "view/<n>",
// where n is this browser's page load today (1, 2, 3 ...; from local storage, reset each day).
// GoatCounter counts each path once per visitor per day, so "view/1" is the day's unique visitors
// and all "view/<n>" together are its page views (up to VIEW_CAP a visitor). Only the number is
// sent: no ID, no cookie. team_stats.py reads these (VIEW_RE) for the team dashboard. On the day's
// first page it also sends "visitor/new" or "visitor/returning" (VISITOR_RE).
(function(){
  const VIEW_CAP = 25;
  const day = new Date().toLocaleDateString('en-CA', {timeZone: 'America/New_York'});
  let n = 1;
  try {
    const v = JSON.parse(localStorage.getItem('psl_views') || 'null');
    n = v && v.d === day ? v.n + 1 : 1;
    localStorage.setItem('psl_views', JSON.stringify({d: day, n}));
  } catch(e) { n = 1; }       // storage blocked: still counted as a visitor
  if (n > VIEW_CAP) return;
  // new or returning: on the first page of the day, whether this browser has been here before
  // (the date of its first visit stays in local storage; only "new" or "returning" is sent)
  let kind = null;
  if (n === 1) {
    kind = 'new';
    try { const first = localStorage.getItem('psl_first'); if (first && first !== day) kind = 'returning'; if (!first) localStorage.setItem('psl_first', day); } catch(e) {}
  }
  let tries = 0;
  (function send(){
    const gc = window.goatcounter;
    if (gc && typeof gc.count === 'function') {
      gc.count({path: 'view/' + n, title: 'Page view ' + n + ' today', event: true});
      if (kind) gc.count({path: 'visitor/' + kind, title: (kind === 'new' ? 'New' : 'Returning') + ' visitor', event: true});
    } else if (++tries < 40) setTimeout(send, 250);   // count.js loads async; give up after 10 s (blocked)
  })();
})();

// ---- outbound clicks: one anonymous GoatCounter event per click on a link that leaves the site,
// e.g. "click/polymarket-site/nfl" (what was clicked, then which page). No ID or cookie.
// team_stats.py reads these for the team dashboard and keeps them out of the visit counts.
(function(){
  const PAGE = (location.pathname.match(/\/(nfl|nba|nhl|mlb)\.html$/) || [])[1] || 'home';
  function kind(u){
    const h = u.hostname.replace(/^www\./,''), p = u.pathname;
    if (/(^|\.)polymarket\.(us|com)$/.test(h)) return /^\/(join|squad)\b/.test(p) ? 'polymarket-signup' : p === '/' ? 'polymarket-site' : 'polymarket-market';
    if (/(^|\.)kalshi\.com$/.test(h)) return /^\/sign-?up/.test(p) ? 'kalshi-signup' : p === '/' ? 'kalshi-site' : 'kalshi-market';
    if (/(^|\.)instagram\.com$/.test(h)) return 'instagram-profile';
    if (/(^|\.)tiktok\.com$/.test(h)) return 'tiktok-profile';
    if (/^(x|twitter)\.com$/.test(h)) return 'x-profile';
    if (/(^|\.)ncpgambling\.org$/.test(h)) return 'gambling-help';
    return 'other-site';
  }
  function onClick(e){
    const a = e.target && e.target.closest && e.target.closest('a[href]'); if (!a) return;
    let u; try { u = new URL(a.href, location.href); } catch(_) { return; }
    if (!/^https?:$/.test(u.protocol) || u.hostname === location.hostname) return;
    const gc = window.goatcounter; if (!gc || typeof gc.count !== 'function') return;
    const k = kind(u) + (a.dataset.place ? '-' + a.dataset.place : '');   // e.g. polymarket-site-sheet
    gc.count({path: 'click/' + k + '/' + PAGE, title: 'Clicked ' + k + ' on ' + PAGE, event: true});
  }
  document.addEventListener('click', onClick, true);
  document.addEventListener('auxclick', e => { if (e.button === 1) onClick(e); }, true);   // middle-click: new tab
})();
