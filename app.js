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
  // A game's start for a pick card, in the visitor's own time zone: "Today 7:10 PM EDT", "Tomorrow 1:05 PM CDT", "Sat 4:25 PM EDT".
  function startLabel(iso){
    const t=Date.parse(iso); if(!isFinite(t)) return '';
    const d=new Date(t), day=x=>x.toLocaleDateString('en-CA'), now=new Date(), tmr=new Date(Date.now()+864e5);
    const when=day(d)===day(now)? 'Today' : day(d)===day(tmr)? 'Tomorrow' : d.toLocaleDateString([], {weekday:'short', month:'short', day:'numeric'});
    return when+' '+d.toLocaleTimeString([], {hour:'numeric', minute:'2-digit', timeZoneName:'short'});
  }
  // The start line under a pick card's matchup, with a live countdown (tickCountdowns keeps it current).
  function gameTime(iso){
    const t=Date.parse(iso); if(!isFinite(t)) return '';
    return `<span class="pc-when">⏰ ${esc(startLabel(iso))} · <i data-cd="${esc(iso)}">${until(t)}</i></span>`;
  }
  // ---- live Polymarket US prices between site updates (NBA, NHL, MLB boards) ----
  // The builders list each upcoming pick's Polymarket US market (the sport file's "us": "pid|stat|line" -> slug);
  // while the page is open and visible this re-reads those markets' best prices once a minute.
  // Display only: which list a pick is on, and its recorded price, still come from the builder.
  const liveUS=(function(){
    const Q=new Map(); let slugs=[], cb=null, timer=null;
    const px=a=>{ const v=a? parseFloat(a.value) : NaN; return v>0 && v<1? v : null; };
    async function one(s){
      try{
        const r=await fetch('https://gateway.polymarket.us/v1/markets/'+encodeURIComponent(s)+'/bbo', {cache:'no-store'});
        if(!r.ok) return;
        const d=(await r.json()).marketData||{}, open=!d.state || d.state==='MARKET_STATE_OPEN';
        const bid=px(d.bestBid), ask=px(d.bestAsk);
        Q.set(s, {over: open? ask : null, under: open && bid!=null? 1-bid : null, at: Date.now()});   // what you'd pay for each side
      }catch(e){}
    }
    const nap=ms=>new Promise(r=>setTimeout(r, ms));
    function schedule(){ clearTimeout(timer); timer=setTimeout(tick, 60000); }
    async function tick(){
      if(document.hidden || !slugs.length){ schedule(); return; }
      const list=slugs.slice(0, 150);
      for(let i=0; i<list.length; i+=6){ await Promise.all(list.slice(i, i+6).map(one)); await nap(350); }   // under Polymarket US's 20 requests/s
      if(cb) cb();
      schedule();
    }
    return {
      start(map, onUpdate){ slugs=[...new Set(Object.values(map||{}))]; cb=onUpdate; if(slugs.length) tick(); },
      quote(s){ const q=s && Q.get(s); return q && Date.now()-q.at < 180000? q : null; }   // 3 minutes old at most
    };
  })();
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
  // A pick card's chance ring. Value cards (o.fair) show the fair chance: on Value picks the model has run 15-20 points
  // above what they hit, and the market price has been the better guide, so the blend is the honest headline;
  // the model's own number stays underneath (Pro view). Every other card shows the model's chance.
  function probRing(prob, o){ o=o||{}; const pv=Math.round(prob*100);
    if(o.fair && o.price!=null){ const fv=Math.round(100*fairOf(prob, o.price)), c=Math.round(o.price*100);
      return `<div class="pc-prob pc-fair"><div class="ring" style="--p:${fv}"><b>${fv}<small>%</small></b></div>`+
        `<span title="${esc(`The model says ${pv}%, the market price ${c}¢. On Value picks the market has been the better guide, so the fair chance blends the two, mostly the market.`)}">fair chance</span>`+
        `<span class="pro-only pc-model">model ${pv}%</span></div>`; }
    return `<div class="pc-prob"><div class="ring" style="--p:${pv}"><b>${pv}<small>%</small></b></div><span${o.title? ` title="${esc(o.title)}"` : ''}>chance</span></div>`; }
  function setFair(w){ if(!(w>=0 && w<=1) || w===FAIR_W) return; FAIR_W=w;
    document.querySelectorAll('.verdict').forEach(el=>{ if(el._o){ el.dataset.sig=''; verdict(el, el._o); } }); }

  // ---- the Player tab's verdict card: the model's chance against the price, in one call ----
  // VALUE uses the site's own two rules (price 30¢+, model 15+ points better); SKIP means
  // the price is above the model's chance; FAIR is everything between. o.listed: the pick is a Value
  // spot under its own page's rules (tennis: 30-80¢, 8-20 points), which then decides VALUE.
  function verdictOf(prob, price, listed){
    const pv=Math.round(prob*100);
    if(price==null) return {k:'none', label:'No price', say:"No Polymarket or Kalshi price for this exact line right now — the model's chance stands on its own. Check the price before you bet."};
    const c=Math.round(price*100), e=Math.round((prob-price)*100), sg=v=>(v>=0?'+':'−')+Math.abs(v);
    const fv=Math.round(100*fairOf(prob, price)), fe=fv-c;
    if(listed!=null && !listed && prob-price>-0.03) return {k:'fair', label:'Fair', say: prob-price>=0.08
      ? `The model is ${sg(e)} over a ${c}¢ price, but this side is outside this page's value rules. Fair chance ${fv}%.`
      : `Fair chance ${fv}% against a ${c}¢ price. The model alone says ${pv}%.`};
    if(listed || (listed==null && price>=0.30 && prob-price>=0.15)) return {k:'value', label:'Value', say:`Clears the value rules: the model says ${pv}% against a ${c}¢ price. The market usually knows more, though — blended, the fair chance is ${fv}%, an expected edge of ${sg(fe)}. A lead to check, not a lock.`};
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
    const pv=Math.round(o.prob*100), v=verdictOf(o.prob, o.price, o.listed);
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
  // o: {name, team, sport, vs, when, prob, lo, hi, neff, side, line, statText, price, live, vals, onOpen, onShare,
  //     watch: {on, toggle() -> bool} (a star in the header), links: {P, K} (exact market URLs, PS.exchangeUrls)}
  function pickSheet(o){
    const v=(o.vals||[]).filter(x=>x!=null && isFinite(x)).slice(-10), hits=v.filter(x=> o.side==='under'? x<+o.line : x>+o.line).length;
    const w=sheet(`<div class="ps-head" style="${teamVars(o.sport, o.team)}"><span class="av">${esc(initialsOf(o.name))}</span>`+
        `<div><b>${esc(o.name)}</b><span><span class="tbadge">${esc(o.team)}</span>${esc(o.vs||'')}${o.when? ' · '+esc(o.when) : ''}</span></div>`+
        (o.watch? `<button type="button" class="ps-star"></button>` : '')+`</div>`+
      `<div class="verdict" hidden></div>`+fastHtml(o)+reasonHtml(o)+
      (v.length>=3? `<div class="ps-l10"><div class="ps-sub">Last ${v.length} games · cleared ${esc(o.line)} <b>${hits} of ${v.length}</b></div>${bigSpark(v, o.line, o.side)}</div>` : '')+
      `<div class="ps-actions"><button type="button" class="btn ps-open">Full breakdown →</button></div>`+
      promoHtml(o)+moreHtml(o.more),
      `${o.name} ${o.side} ${o.line} ${o.statText}`);
    verdict(w.querySelector('.verdict'), o);
    w.querySelector('.ps-open').onclick=()=>{ closeSheet(); if(o.onOpen) o.onOpen(); };
    w.querySelectorAll('.ps-mi').forEach(b=>b.onclick=()=>{ const it=o.more[+b.dataset.g].items[+b.dataset.i]; closeSheet(); it.open(); });
    const sb=w.querySelector('.ps-star');   // o.watch: {on, toggle() -> now starred}
    if(sb){ const paint=on=>{ sb.classList.toggle('on', !!on); sb.setAttribute('aria-pressed', String(!!on));
        sb.setAttribute('aria-label', on? `Remove ${o.name} from your watchlist` : `Star ${o.name} to your watchlist`);
        sb.innerHTML=`<span aria-hidden="true">${on? '\u2605' : '\u2606'}</span><span>${on? 'Watching' : 'Watch'}</span>`; };
      paint(o.watch.on);
      sb.onclick=()=>{ const on=!!o.watch.toggle(); o.watch.on=on; paint(on); toast(on? '\u2605 Added to your watchlist' : 'Removed from your watchlist'); }; }
  }
  // Where to find the pick: the exchange with the cheaper price for this pick first. Plain links, no referral codes.
  // data-place="sheet" makes the click count as "<exchange>-site-sheet" on the team dashboard.
  const REF={P:{name:'Polymarket', href:'https://polymarket.us'},
             K:{name:'Kalshi', href:'https://kalshi.com'}};
  // o.links: {P, K} exact URLs for this game's market (PS.exchangeUrls); each falls back to the exchange's home page.
  const okUrl=u=> typeof u==='string' && /^https:\/\/(polymarket\.us|kalshi\.com)\//.test(u);
  function promoHtml(o){
    const ka=o.vn==='K'? 'K' : 'P', kb=ka==='K'? 'P' : 'K', a=REF[ka], b=REF[kb], L=o.links||{};
    const ha=okUrl(L[ka])? L[ka] : a.href, hb=okUrl(L[kb])? L[kb] : b.href;
    return `<div class="ps-promo"><a class="ps-ref" href="${esc(ha)}" target="_blank" rel="noopener" data-place="sheet"><span>Find this prop on <b>${a.name}</b> →</span></a>`+
      `<a class="ps-ref2" href="${esc(hb)}" target="_blank" rel="noopener" data-place="sheet">or on ${b.name} →</a>`+
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
      const page=(location.pathname.match(/\/(nfl|nba|nhl|mlb|tennis)\.html$/) || [])[1] || 'home', k='view-'+v+(how==='switch'? '-switch' : '');
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
  // the question existed gets just the question. Only a sport board asks it (the views differ nowhere
  // else), so a visitor landing on the home page gets one tap, and the question on their first board. ----
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
    const board=/\/(nfl|nba|nhl|mlb|tennis)\.html$/.test(location.pathname);   // PAGE_SPORT is declared further down
    if(!document.body || (ok && (!board || viewAsked()))) return;
    const g=document.createElement('div'); g.className='psgate'; g.setAttribute('role','dialog'); g.setAttribute('aria-modal','true'); g.setAttribute('aria-labelledby','psgate-h');
    g.innerHTML=`<div class="psgate-card"></div>`;
    const card=g.firstChild, close=()=>{ g.remove(); document.documentElement.classList.remove('ps-lock'); };
    document.body.appendChild(g); document.documentElement.classList.add('ps-lock');
    if(ok){ viewStep(card, close); return; }
    card.innerHTML=GATE_LOGO+
      `<h2 id="psgate-h">Are you 18 or older?</h2>`+
      `<p>Prop Streak Lab is player-prop research for adults. It isn't a sportsbook and takes no bets. Some links go to Polymarket and Kalshi, which have their own age and location rules.</p>`+
      `<div class="psgate-btns"><button type="button" class="btn" id="psgate-ok">Yes, I'm 18 or older</button><a class="btn ghost" href="https://www.google.com" rel="noopener">No, leave</a></div>`+
      `<p class="psgate-fine">We use only essential local storage for your preferences and cookieless analytics — no ads, no cross-site tracking. <a href="/cookies.html">Cookie Policy</a> · <a href="/privacy.html">Privacy</a><br>Gambling problem? Call 1-800-522-4700 or visit <a href="https://www.ncpgambling.org" rel="noopener" target="_blank">ncpgambling.org</a>.</p>`;
    const bar=document.getElementById('pslcookie'); if(bar) bar.hidden=true;    // the check carries the same notice
    const btn=g.querySelector('#psgate-ok'); btn.focus({preventScroll:true});
    btn.onclick=()=>{ try{ localStorage.setItem('psl_age_ok','1'); localStorage.setItem('psl_notice_ok','1'); }catch(e){}
      if(board && canStore() && !viewAsked()) viewStep(card, close); else close(); };
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
  const PAGE_SPORT=(location.pathname.match(/\/(nfl|nba|nhl|mlb|tennis)\.html$/)||[])[1]||null;
  const SPORT_LBL={nfl:'NFL', nba:'NBA', nhl:'NHL', mlb:'MLB', tennis:'Tennis'};

  // share pages that exist for this board's picks (p/keys.json, build_games.py): {sport: {key: expiry}}
  let SHARE_KEYS=null;
  const shareKey=st=> `${st.player.id}-${st.stat}-${String(Number(st.line))}-${st.ou}`;   // = build_games.share_key
  if(PAGE_SPORT) fetch('p/keys.json',{cache:'no-cache'}).then(r=>r.ok? r.json() : null)
    .then(d=>{ SHARE_KEYS=new Set(Object.keys((d&&d[PAGE_SPORT])||{})); }).catch(()=>{});
  // props whose price moved 10c+ in the last hour (today.json "fast", build_today.fast_moves): a warning in the pick sheet
  let FAST=[];
  if(PAGE_SPORT) fetch('today.json',{cache:'no-cache'}).then(r=>r.ok? r.json() : null)
    .then(d=>{ FAST=((d&&d.fast)||[]).filter(f=>f.sport===PAGE_SPORT); }).catch(()=>{});
  // Plain-English reasons for a pick, from its own numbers: the last games against the line, the
  // streak, the average against the line, and the model against the market price.
  function reasonHtml(o){
    // o.why: the page's own reasons (trusted markup, data escaped), for markets a game log doesn't fit (tennis)
    if(o.why) return o.why.length? `<div class="ps-why"><b>Why</b><ul>${o.why.map(x=>`<li>${x}</li>`).join('')}</ul></div>` : '';
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
        `<a class="tr-how" href="/record.html">The full record, losses included →</a><a class="tr-how" href="/methodology.html">How the model works →</a>`;
      el.hidden=false;
      const go=el.querySelector('[data-tab-go]');
      if(go) go.onclick=e=>{ const tab=document.querySelector(`.tab[data-tab="${go.dataset.tabGo}"]`); if(tab){ e.preventDefault(); tab.click(); } };
    };
    paint(null);
    fetch('today.json',{cache:'no-cache'}).then(r=>r.ok? r.json() : null).then(t=>{ if(t){ paint(t); if(t.fair) setFair(t.fair.w); } }).catch(()=>{});
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
    box.innerHTML='<p class="psnew-line simple-only"><span><b>72%</b> = the chance it hits (on Value picks, the <i>fair</i> chance: our model blended with the market, which has been the better guide there) · <b>57¢</b> = the price, so it pays 1.75× · Tap a pick for the full story. Research, not advice. 18+.</span>'+
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

  // ---- the price since the pick was listed, as a tiny line (today.json's sp: cents, oldest first, one point
  // about every 30 minutes or on each change; build_today.py keeps them). Up = toward the pick. Nothing for
  // fewer than 3 points or a move under 2 cents. ----
  function pxSpark(sp){
    const v=(sp||[]).map(Number).filter(x=>isFinite(x));
    if(v.length<3) return '';
    const lo=Math.min(...v), hi=Math.max(...v);
    if(hi-lo<2) return '';
    const W=56, H=18, d=v[v.length-1]-v[0];
    const pts=v.map((x,i)=>`${(i*(W-4)/(v.length-1)+2).toFixed(1)},${(H-2-(x-lo)*(H-4)/(hi-lo)).toFixed(1)}`);
    const last=pts[pts.length-1].split(',');
    const cls=d>=1?'up':d<=-1?'dn':'flat';
    const say=`Price since it was listed: ${v[0]}\u00a2 \u2192 ${v[v.length-1]}\u00a2 (low ${lo}\u00a2, high ${hi}\u00a2)`;
    return `<svg class="pxs ${cls}" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(say)}"><title>${esc(say)}</title>`+
      `<polyline points="${pts.join(' ')}" fill="none" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>`+
      `<circle cx="${last[0]}" cy="${last[1]}" r="2.2"/></svg>`;
  }

  // ---- The Value record banner at the top of every sport page (one look on every board). opts:
  //   r: the Value list's season record {n, hit, priced, units} (units at the recorded price, 1 unit a pick)
  //   pre: an older rule's record, named under the banner (NBA's and MLB's "Vpre"), or null
  //   season: the label after "Value spots ·" ("this season", "2026 season")
  //   rule: one line on what the list takes now; preRule: what the old rule took (for the note)
  //   live: how many Value spots are on the board now (shown when nothing is graded yet)
  //   onRecord / onLive: what a tap does (Past picks / scroll to the Value panel)
  // Losses show in red; nothing at all hides the banner. ----
  function valueBanner(el, o){
    if(!el) return;
    o=o||{};
    const r=o.r, pre=o.pre;
    const u=x=>(x>=0?'+':'−')+Math.abs(+x||0).toFixed(1)+'u';
    el.classList.add('scoreboard');
    if(r && r.n && r.priced){
      const units=+r.units||0, up=units>=0, roi=units/r.priced;
      const preNote=pre && pre.n? ` Value under the old rule${o.preRule? ' ('+esc(o.preRule)+')' : ''}: ${u(pre.units)} on ${pre.n} picks, shown on the <a href="/record.html">Record page</a>.` : '';
      el.innerHTML=`<a class="sb${up?'':' dn'}" href="#past"><span class="sb-k">⚡ Value spots · ${esc(o.season||'this season')}</span>`+
        `<span class="sb-v">${u(units)}</span>`+
        `<span class="sb-s">${r.hit}/${r.n} hit (${Math.round(100*r.hit/r.n)}%) · ${roi>=0?'+':''}${(roi*100).toFixed(1)}% return</span>`+
        (o.rule? `<span class="sb-n">${esc(o.rule)}</span>` : '')+`</a>`+
        `<p class="sb-more">1 unit on every pick at the price it was recorded at, graded from the results.${preNote} <a href="/record.html">The full record →</a></p>`;
      el.querySelector('a.sb').onclick=e=>{ e.preventDefault(); if(o.onRecord) o.onRecord(); };
      el.hidden=false; return;
    }
    if(!o.live){ el.hidden=true; el.innerHTML=''; return; }
    el.innerHTML=`<a class="sb" href="#valuepanel"><span class="sb-k">⚡ Value spots</span><span class="sb-v">${o.live} live now</span>`+
      `<span class="sb-s">${esc(o.liveText||"Where the model's chance clearly beats the market price.")}</span></a>`;
    el.querySelector('a.sb').onclick=e=>{ e.preventDefault(); if(o.onLive) o.onLive(); };
    el.hidden=false;
  }

  // ---- The games strip on every sport page: one chip per upcoming game (or match), its start time and how many
  // of its picks are on a list; a tap picks that game in the filter bar, a second tap clears it. opts:
  //   games: [{key, label, start, listed, n}] (key = the filter bar's game value), current: the selected key,
  //   onPick(key or ''), label: the strip's name ("Games", "Matches"). Hidden with fewer than two. ----
  function gameStrip(el, o){
    if(!el) return;
    o=o||{};
    const games=(o.games||[]).slice().sort((a,b)=>String(a.start||'').localeCompare(String(b.start||'')));
    el.classList.add('gamestrip');
    if(games.length<2){ el.hidden=true; el.innerHTML=''; return; }
    el.innerHTML=`<span class="gs-lbl">${esc(o.label||'Games')}</span>`+games.map(g=>
      `<button type="button" class="gs" data-g="${esc(g.key)}" aria-pressed="${g.key===o.current}"><b>${esc(g.label)}</b>`+
      `<span>${esc(g.start? startLabel(g.start) : 'time TBA')} · ${g.listed? g.listed+' on a list' : (g.n||0)+' props'}</span></button>`).join('');
    el.hidden=false;
    el.querySelectorAll('.gs').forEach(b=>b.onclick=()=>{ if(o.onPick) o.onPick(b.dataset.g===o.current? '' : b.dataset.g); });
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
  // The main price of a pick whose best price is a thin Polymarket one (Kalshi thin too, or not listing it): no number.
  function thinPrice(){ return `<span class="pmdim" title="Less than $25 is offered near the Polymarket price for this side, so there\u2019s no price you can really get right now">not enough offered</span>`; }
  function venueName(vn){ return vn==='K'? 'Kalshi' : 'Polymarket'; }
  // thinP/thinK: under $25 is offered within 2\u00a2 of that price (depth.py), so a bet would move it.
  // A thin Polymarket price isn't shown at all: on Polymarket US one side of a prop often has a dollar or two
  // behind it (NBA unders), so the number isn't a price you can actually get. It reads "not enough offered".
  function venues(pp, kp, vn, thinP, thinK){
    if(pp==null && kp==null) return '';
    const one=(name, v, on, thin)=>`<span class="vq${on?' best':''}${thin && v!=null?' thin':''}">${name} <b>${v==null? '\u2014' : Math.round(v*100)+'\u00a2'}</b>${thin && v!=null? ' <i>thin</i>' : ''}</span>`;
    const pmOne=(on)=> pp!=null && thinP
      ? `<span class="vq thin" title="Less than $25 is offered near this price on Polymarket, so it isn\u2019t a price you can really get">Polymarket <i>not enough offered</i></span>`
      : one('Polymarket', pp, on, false);
    const title=`What you'd pay for this side on each exchange (\u2014 = not listed at this line). The highlighted one is the price the edge, Top 25 Surest and Value use: the cheaper exchange with $25+ offered within 2\u00a2 of its price. \u201cthin\u201d = less than that is offered, so a bet would move the price.`;
    return `<span class="venues" title="${esc(title)}">${pmOne(vn!=='K' && pp!=null)}${one('Kalshi', kp, vn==='K', thinK)}</span>`;
  }

  // ---- locked picks: the builders lock a pick when its game starts within 30 minutes (lock_picks) ----
  // From then on its spot on the lists, its chance and its price stay as published.
  // Shown under every pick list, locked picks or not: one line, tap to read when and why picks lock
  // (open by default while a pick on the list is locked).
  function lockNote(anyLocked){
    return `<details class="mktnote locknote"${anyLocked?' open':''}><summary><span class="lockbadge">\ud83d\udd12 ${anyLocked?'Locked':'Lock rule'}</span><span>${anyLocked?'Locked picks are final.':'Picks lock 20\u201330 minutes before the start.'} <u>When and why</u></span></summary><div>`+
      `<p><b>When:</b> a pick locks once its game starts within 30 minutes. The site updates about every 10 minutes, so that\u2019s 20\u201330 minutes before the start.</p>`+
      `<p><b>What stops changing:</b> whether it\u2019s on Top 25 or Value, the model\u2019s chance, and its price. No new picks are added for that game.</p>`+
      `<p><b>Why:</b> so the record shows exactly what you saw before the game. Each pick is graded at its locked price, a last-minute update can\u2019t swap a pick you already acted on, and prices right before the start are the least reliable. <a href="/methodology.html#locking">How locking works</a></p></div></details>`;
  }
  // A strip across the top of a locked pick's card, so a final pick reads as final at a glance.
  function lockRibbon(lk){
    const t=Date.parse(lk), at=isFinite(t)? ' at '+new Date(t).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'}) : '';
    return `<div class="lockribbon" title="${esc(`Locked${at}: the game starts within 30 minutes, so this pick is final.`)}"><b>🔒 Locked</b><span>Game starts soon · final pick</span></div>`;
  }
  function lockBadge(lk){
    const t=Date.parse(lk), at=isFinite(t)? ' at '+new Date(t).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'}) : '';
    return `<span class="lockbadge" title="${esc(`Locked${at}: the game starts within 30 minutes, so this pick is final \u2014 its Top 25 / Value status, its chance and its price won\u2019t change again.`)}">\ud83d\udd12 Locked</span>`;
  }

  // ---- parlay finder (every sport page's Tools tab): a payout range and a chance floor in, the parlay with
  // the highest model chance whose real payout lands in the range out. ----
  // legs: [{key, gid, pid, name, team, opp, side, line, statText, prob, price, vn}], price a fraction you'd
  // actually pay (the page leaves out thin and locked ones). The payout is 1 / the product of the prices and
  // the chance the product of the model's chances: legs are treated as independent, which is why legs from
  // one game are left out unless asked for (they move together). A beam search over the legs, likeliest
  // first, keeps the BEAM best partial parlays at each size; it's exact for small boards and close otherwise.
  // PF_MIN_GAMES: the history a leg needs (n: effective games, when the page has it), the Value lists' rule, so a
  // rookie's 95% on three games can't anchor a parlay. A parlay is 2+ legs.
  const PF_BEAM=400, PF_MIN_PX=0.05, PF_MAX_PX=0.97, PF_MIN_GAMES=6;
  function parlaySearch(legs, o){
    const lo=Math.log(Math.max(1.01, o.min)), hi=Math.log(Math.max(o.min, o.max)), floor=Math.log(Math.max(1e-6, o.chance||1e-6));
    const pool=[], seenK=new Set();
    legs.filter(l=>l && l.prob>0 && l.prob<1 && l.price>=PF_MIN_PX && l.price<=PF_MAX_PX && (l.n==null || l.n>=PF_MIN_GAMES))
      .sort((a,b)=>b.prob-a.prob).forEach(l=>{ if(!seenK.has(l.key)){ seenK.add(l.key); pool.push(l); } });
    let beam=[{idx:-1, legs:[], lp:0, lpay:0}];
    const found=[];
    for(let size=1; size<=o.maxLegs && beam.length; size++){
      const next=[];
      beam.forEach(s=>{
        const pids=new Set(s.legs.map(l=>String(l.pid))), gids=new Set(s.legs.map(l=>String(l.gid)));
        for(let i=s.idx+1;i<pool.length;i++){
          const l=pool[i];
          if(pids.has(String(l.pid)) || (!o.sameGame && gids.has(String(l.gid)))) continue;
          const lp=s.lp+Math.log(l.prob), lpay=s.lpay-Math.log(l.price);
          if(lp<floor || lpay>hi+1e-9) continue;          // below the chance floor, or past the top of the payout range
          const st={idx:i, legs:s.legs.concat(l), lp, lpay};
          next.push(st);
          if(lpay>=lo-1e-9 && size>=2) found.push(st);
        }
      });
      next.sort((a,b)=>b.lp-a.lp || b.lpay-a.lpay);
      beam=next.slice(0, PF_BEAM);
    }
    const sig=s=>s.legs.map(l=>l.key).sort().join('|'), out=[], seen=new Set();
    found.sort((a,b)=>b.lp-a.lp || (b.lp+b.lpay)-(a.lp+a.lpay)).forEach(s=>{ const k=sig(s); if(!seen.has(k) && out.length<12){ seen.add(k); out.push(s); } });
    return {results:out.map(s=>({legs:s.legs, prob:Math.exp(s.lp), payout:Math.exp(s.lpay)})), pool:pool.length};
  }
  function parlayFinder(el, cfg){
    if(!el) return;
    const KEY='psl_pf_'+cfg.sport, saved=(()=>{ try{ return JSON.parse(localStorage.getItem(KEY)||'{}'); }catch(e){ return {}; } })();
    const v={min:saved.min||1.4, max:saved.max||1.6, chance:saved.chance!=null? saved.chance : 75, maxLegs:saved.maxLegs||4, sameGame:!!saved.sameGame};
    el.innerHTML=
      `<div class="pfform">`+
        `<div class="pfrow"><span class="pflab">Pays</span><input id="pfmin" type="number" min="1.05" step="0.05" value="${v.min}" aria-label="Lowest payout (times your stake)"><span>x to</span>`+
          `<input id="pfmax" type="number" min="1.05" step="0.05" value="${v.max}" aria-label="Highest payout (times your stake)"><span>x</span></div>`+
        `<div class="pfchips">${[1.5,2,3,5].map(x=>`<button type="button" class="chip" data-x="${x}">${x}x</button>`).join('')}</div>`+
        `<div class="pfrow"><span class="pflab">Model chance at least</span><input id="pfchance" type="number" min="1" max="99" step="1" value="${v.chance}" aria-label="Lowest combined chance, percent"><span>%</span></div>`+
        `<div class="pfrow"><span class="pflab">Up to</span><select id="pflegs" aria-label="Most legs">${[2,3,4,5,6,8].map(n=>`<option${n===v.maxLegs?' selected':''}>${n}</option>`).join('')}</select><span>legs</span>`+
          `<label class="pfsg"><input id="pfsg" type="checkbox"${v.sameGame?' checked':''}> allow legs from the same ${esc(cfg.gameWord||'game')}</label></div>`+
        `<button id="pfgo" class="btn" type="button">Find my parlay</button>`+
      `</div><div id="pfout" aria-live="polite"></div>`;
    const $=id=>el.querySelector('#'+id), out=$('pfout');
    let results=[], at=0;
    el.querySelectorAll('.pfchips .chip').forEach(b=>b.onclick=()=>{ const x=+b.dataset.x; $('pfmin').value=(x*0.93).toFixed(2); $('pfmax').value=(x*1.07).toFixed(2); });
    const legRow=l=>`<li><button type="button" class="pfleg" data-k="${esc(l.key)}"><span class="pfwho"><b>${esc(l.name)}</b>${l.team? ` <span class="tbadge">${esc(l.team)}</span>` : ''}${l.opp? ` <span class="mktmuted">vs ${esc(l.opp)}</span>` : ''}</span>`+
      `<span class="pfbet"><span class="leantag ${esc(l.side)}">${esc(l.side)}</span> ${esc(l.line)} ${esc(l.statText)}</span>`+
      `<span class="pfnum">${Math.round(l.prob*100)}% <span class="mktmuted">\u00b7 ${Math.round(l.price*100)}\u00a2 ${esc(venueName(l.vn))}</span></span></button></li>`;
    function show(){
      const r=results[at]; if(!r) return;
      const mkt=1/r.payout, ev=r.prob*r.payout-1;
      out.innerHTML=`<div class="pfres"><div class="parlaysum">`+
          `<div><div class="lab">Pays</div><div class="big">${r.payout.toFixed(2)}x</div><div class="sub">$10 returns $${(10*r.payout).toFixed(2)}</div></div>`+
          `<div><div class="lab">Model chance</div><div class="big ${r.prob>=0.5?'hit':''}">${Math.round(r.prob*100)}%</div><div class="sub">all ${r.legs.length} legs hit</div></div>`+
          `<div><div class="lab">Market's chance</div><div class="big">${Math.round(mkt*100)}%</div><div class="sub">what the prices imply</div></div>`+
          `<div><div class="lab">Model edge</div><div class="big">${ev>=0?'+':'\u2212'}${Math.abs(Math.round(ev*100))}%</div><div class="sub">expected return per $1</div></div>`+
        `</div><ol class="pflegs">${r.legs.map(legRow).join('')}</ol>`+
        `<p class="mktnote">Parlay ${at+1} of ${results.length} that fit${results.length>1? ' \u00b7 <button type="button" class="linkbtn" id="pfnext">show another</button>' : ''}. `+
        `The payout is each leg's current price multiplied together (the cheaper of Polymarket and Kalshi with $25+ offered); prices move, so check them before you bet. `+
        `The chance treats the legs as independent. When the model's chance is well above the market's, the market is usually seeing something the model can't (injuries, lineups, news), so read a big gap as a reason to check, not a sure thing. Research, not betting advice.</p></div>`;
      const nx=out.querySelector('#pfnext'); if(nx) nx.onclick=()=>{ at=(at+1)%results.length; show(); };
      out.querySelectorAll('.pfleg').forEach(b=>b.onclick=()=>{ const l=r.legs.find(x=>x.key===b.dataset.k); if(l && cfg.open) cfg.open(l); });
    }
    $('pfgo').onclick=async()=>{
      let min=parseFloat($('pfmin').value), max=parseFloat($('pfmax').value);
      const chance=Math.min(99, Math.max(1, parseFloat($('pfchance').value)||1))/100, maxLegs=parseInt($('pflegs').value,10)||4, sameGame=$('pfsg').checked;
      if(!(min>1)){ out.innerHTML='<p class="mktnote">Set a payout above 1x.</p>'; return; }
      if(!(max>=min)) max=min;
      try{ localStorage.setItem(KEY, JSON.stringify({min, max, chance:Math.round(chance*100), maxLegs, sameGame})); }catch(e){}
      out.innerHTML='<p class="mktnote">Searching every priced pick\u2026</p>';
      let legs=[];
      try{ legs=(await cfg.getLegs())||[]; }catch(e){ legs=[]; }
      const res=parlaySearch(legs, {min, max, chance, maxLegs, sameGame});
      results=res.results; at=0;
      if(results.length){ show(); return; }
      if(!res.pool){ out.innerHTML=`<p class="mktnote">No priced picks to build from right now: a leg needs a live Polymarket or Kalshi price with $25+ offered, on a ${esc(cfg.gameWord||'game')} that hasn't started. ${esc(cfg.emptyNote||'')}</p>`; return; }
      // Nothing clears the chance floor: say what the board can do at that payout, and at that chance.
      const best=parlaySearch(legs, {min, max, chance:0, maxLegs, sameGame}).results[0];
      const maxPay=parlaySearch(legs, {min:1.01, max:100, chance, maxLegs, sameGame}).results.sort((a,b)=>b.payout-a.payout)[0];
      out.innerHTML=`<p class="mktnote"><b>No parlay paying ${min.toFixed(2)}\u2013${max.toFixed(2)}x reaches a ${Math.round(chance*100)}% model chance</b> from the ${res.pool} priced picks on the board.`+
        (best? ` The likeliest one in that payout range is <b>${Math.round(best.prob*100)}%</b> (the market says ${Math.round(100/best.payout)}%).` : ` Nothing on the board lands in that payout range with up to ${maxLegs} legs.`)+
        (maxPay? ` At ${Math.round(chance*100)}% or better, the most it can pay is about <b>${maxPay.payout.toFixed(2)}x</b>.` : '')+
        ` A payout and a chance trade off: at fair prices, 1.5x is about a 67% chance and 2x about 50%, so asking for both a big payout and a high chance means asking for picks the market has badly wrong.</p>`+
        (best? `<p class="mktnote"><button type="button" class="linkbtn" id="pfshowbest">Show the likeliest ${min.toFixed(2)}\u2013${max.toFixed(2)}x parlay anyway</button></p>` : '');
      const sb=out.querySelector('#pfshowbest');
      if(sb) sb.onclick=()=>{ results=parlaySearch(legs, {min, max, chance:0, maxLegs, sameGame}).results; at=0; show(); };
    };
  }

  // ======== daily tools, shared by every sport page: filter bar, watchlist, line ladder, exact-market
  // links, bet calculator and parlay slip. Everything is saved on this device only (localStorage, and the
  // page still works when storage is blocked). Prices may come in as fractions or the NFL's cents. ========
  const lsGet=(k, d)=>{ try{ const v=JSON.parse(localStorage.getItem(k)); return v==null? d : v; }catch(e){ return d; } };
  const lsSet=(k, v)=>{ try{ localStorage.setItem(k, JSON.stringify(v)); }catch(e){} };
  const frac=x=>{ if(x==null || x==='') return null; const v=+x; return isFinite(v)? (v>1? v/100 : v) : null; };
  const pctTxt=p=>{ const v=p*100; return (v>0 && v<10? v.toFixed(1) : Math.round(v))+'%'; };
  const multTxt=m=> m>=100? Math.round(m).toLocaleString()+'×' : m.toFixed(m<10? 2 : 1)+'×';
  const SPORT_NAME={nfl:'NFL', nba:'NBA', nhl:'NHL', mlb:'MLB', tennis:'Tennis'};
  const listTags=lists=>{ const s=lists===true? 'L' : String(lists||'');
    return (s.includes('T')? '<span class="pst-tag top">on Top 25</span>' : '')+(s.includes('V')? '<span class="pst-tag val">on Value</span>' : '')+
      (s==='L'? '<span class="pst-tag">on a list</span>' : ''); };

  // ---- watchlist across sports: [{sport, pid, name, team}] in psl_watch_all. The older per-sport lists
  // (pids only: psl_watch for the NFL, psl_<sport>_watch for the others) are copied in once and kept,
  // and every change is written back to them too, so a page that still reads its own list agrees. ----
  const WATCH_KEY='psl_watch_all', WATCH_MIG='psl_watch_mig',
        WATCH_OLD={nfl:'psl_watch', nba:'psl_nba_watch', nhl:'psl_nhl_watch', mlb:'psl_mlb_watch', tennis:'psl_tennis_watch'};
  let WL=null; const wFns=[];
  function wLoad(){
    if(WL) return WL;
    const raw=lsGet(WATCH_KEY, []), mig=lsGet(WATCH_MIG, {}) || {};
    let a=(Array.isArray(raw)? raw : []).filter(x=>x && x.sport && x.pid!=null && x.pid!=='')
      .map(x=>({sport:String(x.sport), pid:String(x.pid), name:String(x.name||''), team:String(x.team||'')}));
    let changed=false;
    Object.keys(WATCH_OLD).forEach(sp=>{
      if(mig[sp]) return;
      const old=lsGet(WATCH_OLD[sp], []);
      if(Array.isArray(old)) old.forEach(pid=>{ if(pid==null || pid==='') return; pid=String(pid);
        if(!a.some(x=>x.sport===sp && x.pid===pid)) a.push({sport:sp, pid, name:'', team:''}); });
      mig[sp]=1; changed=true;
    });
    WL=a;
    if(changed){ lsSet(WATCH_KEY, a); lsSet(WATCH_MIG, mig); }
    return WL;
  }
  function wSave(){
    lsSet(WATCH_KEY, WL);
    Object.keys(WATCH_OLD).forEach(sp=>{   // keep each sport's older list in step (same ids, its own types kept)
      const old=lsGet(WATCH_OLD[sp], null), mine=WL.filter(x=>x.sport===sp).map(x=>x.pid);
      const base=Array.isArray(old)? old.filter(id=>mine.includes(String(id))) : [];
      mine.forEach(id=>{ if(!base.some(b=>String(b)===id)) base.push(id); });
      if(Array.isArray(old) || base.length) lsSet(WATCH_OLD[sp], base);
    });
    wFns.slice().forEach(fn=>{ try{ fn(watch.list()); }catch(e){} });
  }
  const watch={
    list(){ return wLoad().map(x=>Object.assign({}, x)); },
    has(sport, pid){ return pid!=null && wLoad().some(x=>x.sport===String(sport) && x.pid===String(pid)); },
    // adds or removes; returns true when the player is now starred
    toggle(p){
      if(!p || !p.sport || p.pid==null || p.pid==='') return false;
      const a=wLoad(), sp=String(p.sport), id=String(p.pid), i=a.findIndex(x=>x.sport===sp && x.pid===id);
      if(i>=0) a.splice(i, 1); else a.push({sport:sp, pid:id, name:String(p.name||''), team:String(p.team||'')});
      wSave(); return i<0;
    },
    // fills in a starred player's name/team (an entry copied from an older list has only the id); no-op otherwise
    note(sport, pid, name, team){
      const x=wLoad().find(y=>y.sport===String(sport) && y.pid===String(pid));
      if(!x || (!name || x.name===String(name)) && (!team || x.team===String(team))) return;
      if(name) x.name=String(name); if(team) x.team=String(team); lsSet(WATCH_KEY, WL);
    },
    onChange(fn){ if(typeof fn==='function') wFns.push(fn); return ()=>{ const i=wFns.indexOf(fn); if(i>=0) wFns.splice(i, 1); }; }
  };
  // another tab changed the list
  window.addEventListener('storage', e=>{ if(e.key===WATCH_KEY){ WL=null; wFns.slice().forEach(fn=>{ try{ fn(watch.list()); }catch(err){} }); } });

  // A star button for a player. player: {pid|id, name|n, team|t}; opts.label: also say "Watch"/"Watching".
  // One delegated listener toggles it (before any card's own click handler) and repaints every star for that player.
  function starInner(on, label){ return `<span aria-hidden="true">${on? '★' : '☆'}</span>${label? `<span>${on? 'Watching' : 'Watch'}</span>` : ''}`; }
  function starBtn(sport, player, opts){
    const p=player||{}, pid=p.pid!=null? p.pid : p.id, name=p.name!=null? p.name : (p.n||''), team=p.team!=null? p.team : (p.t||'');
    const on=watch.has(sport, pid), label=!!(opts && opts.label);
    return `<button type="button" class="psstar${on? ' on' : ''}${label? ' wl' : ''}" data-star-sport="${esc(sport)}" data-star-pid="${esc(pid)}" data-star-name="${esc(name)}" data-star-team="${esc(team)}"`+
      ` aria-pressed="${on}" aria-label="${esc((on? 'Remove ' : 'Star ')+(name||'this player')+(on? ' from' : ' to')+' your watchlist')}" title="${on? 'On your watchlist' : 'Add to your watchlist'}">${starInner(on, label)}</button>`;
  }
  function paintStars(){
    document.querySelectorAll('.psstar').forEach(b=>{
      const on=watch.has(b.dataset.starSport, b.dataset.starPid), name=b.dataset.starName||'this player';
      if(b.getAttribute('aria-pressed')===String(on)) return;
      b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on));
      b.setAttribute('aria-label', (on? 'Remove ' : 'Star ')+name+(on? ' from' : ' to')+' your watchlist');
      b.title= on? 'On your watchlist' : 'Add to your watchlist';
      b.innerHTML=starInner(on, b.classList.contains('wl'));
    });
  }
  watch.onChange(paintStars);
  document.addEventListener('click', e=>{
    const b=e.target && e.target.closest && e.target.closest('.psstar'); if(!b) return;
    e.preventDefault(); e.stopPropagation();
    const on=watch.toggle({sport:b.dataset.starSport, pid:b.dataset.starPid, name:b.dataset.starName, team:b.dataset.starTeam});
    toast(on? '★ Added to your watchlist' : 'Removed from your watchlist');
  }, true);

  // Every starred player. cfg: {sport, legsForPlayer(pid) -> [{statText, side, line, prob, price, vn, thin, lists}],
  // open(pid), player(pid) -> {name, team} (optional: fills in names copied from an older list)}.
  // This sport's players come with their upcoming priced props; other sports' are links to their page.
  // Repaints itself when the list changes.
  function renderWatchlist(el, cfg){
    if(!el) return;
    el._pswCfg=cfg||{};
    if(!el._pswSub){ el._pswSub=watch.onChange(()=>{ if(el.isConnected) renderWatchlist(el, el._pswCfg); }); }
    const c=el._pswCfg, sp=String(c.sport||''), all=watch.list();
    if(typeof c.player==='function') all.forEach(x=>{ if(x.sport===sp && !x.name){ let p=null; try{ p=c.player(x.pid); }catch(e){}
      if(p && (p.name||p.n)){ x.name=String(p.name||p.n); x.team=String(p.team||p.t||x.team||''); watch.note(sp, x.pid, x.name, x.team); } } });
    if(!all.length){
      el.innerHTML=`<div class="psw-empty"><p class="mktnote"><b>No players starred yet.</b> Tap the <span class="psw-ic" aria-hidden="true">☆</span> star next to any player, on a pick or on their page, and they show up here with today's props. Your list covers every sport and is saved on this device only.</p></div>`;
      return;
    }
    const mine=all.filter(x=>x.sport===sp), others=all.filter(x=>x.sport!==sp);
    const legRow=l=>{
      const px=frac(l.price), prob=frac(l.prob);
      const price= px==null? '<span class="mktmuted">no price</span>' : l.thin? '<span class="mktmuted">not enough offered</span>'
        : `<b>${Math.round(px*100)}¢</b> <span class="mktmuted">${esc(venueName(l.vn))}</span>`;
      return `<li><span class="psw-bet"><span class="leantag ${esc(l.side)}">${esc(l.side)}</span> ${esc(l.line)} ${esc(l.statText)}${listTags(l.lists)}</span>`+
        `<span class="psw-num">${prob!=null? `<b>${Math.round(prob*100)}%</b>` : '—'} <span class="psw-px">${price}</span></span></li>`;
    };
    const mineHtml=mine.map(x=>{
      let legs=[]; try{ legs=(c.legsForPlayer && c.legsForPlayer(x.pid))||[]; }catch(e){ legs=[]; }
      legs=legs.filter(Boolean).slice().sort((a,b)=>((b.lists? 1 : 0)-(a.lists? 1 : 0)) || ((frac(b.prob)||0)-(frac(a.prob)||0))).slice(0, 6);
      return `<div class="psw-p"><div class="psw-h">${starBtn(sp, x)}<button type="button" class="psw-open" data-pid="${esc(x.pid)}"><b>${esc(x.name||'Player '+x.pid)}</b>`+
          `${x.team? ` <span class="tbadge" style="${teamVars(sp, x.team)}">${esc(x.team)}</span>` : ''}<span class="psw-go" aria-hidden="true">›</span></button></div>`+
        (legs.length? `<ul class="psw-legs">${legs.map(legRow).join('')}</ul>` : `<p class="psw-none">No priced props for an upcoming game right now.</p>`)+`</div>`;
    }).join('');
    const bySport={}; others.forEach(x=>{ (bySport[x.sport]=bySport[x.sport]||[]).push(x); });
    const othersHtml=Object.keys(bySport).map(s=>`<div class="psw-o"><div class="ps-sub">${esc(SPORT_NAME[s]||s.toUpperCase())}</div>`+
      bySport[s].map(x=>`<div class="psw-orow">${starBtn(s, x)}<a href="${esc(encodeURIComponent(s)+'.html#player/'+encodeURIComponent(x.pid))}">${esc(x.name||'Player '+x.pid)}`+
        `${x.team? ` <span class="mktmuted">${esc(x.team)}</span>` : ''} <span aria-hidden="true">→</span></a></div>`).join('')+`</div>`).join('');
    el.innerHTML=`<div class="psw">`+(mine.length? mineHtml : `<p class="mktnote">No ${esc(SPORT_NAME[sp]||sp)} players starred yet — tap ☆ next to one.</p>`)+
      (othersHtml? `<div class="psw-others"><div class="psw-oh">Starred in other sports</div>${othersHtml}</div>` : '')+`</div>`;
    el.querySelectorAll('.psw-open').forEach(b=>b.onclick=()=>{ if(c.open) c.open(b.dataset.pid); });
  }

  // ---- filter bar: game, prop, side, price band and starred players, remembered per sport on this device.
  // cfg: {key (the sport), sport (for "starred only"; defaults to key), options:{games:[[value,label]], stats:[[value,label]]},
  // onChange(filters)}. Returns {get(), test(row), set(filters), setOptions(options), clear()};
  // row: {gid, sk, side, price, pid, sport}. ----
  const PRICE_BANDS=[['lt30','Under 30¢',0,0.30],['30-50','30–50¢',0.30,0.50],['50-70','50–70¢',0.50,0.70],['70p','70¢+',0.70,1.01]];
  function filterBar(el, cfg){
    cfg=cfg||{};
    const KEY='psl_flt_'+String(cfg.key||'x'), sport=String(cfg.sport||cfg.key||'');
    let opts={games:[], stats:[]};
    const blank={game:'', stat:'', side:'', band:'', star:false};
    const saved=lsGet(KEY, {}) || {};
    const F=Object.assign({}, blank, {game:String(saved.game||''), stat:String(saved.stat||''), side:['over','under'].includes(saved.side)? saved.side : '',
      band:PRICE_BANDS.some(b=>b[0]===saved.band)? saved.band : '', star:!!saved.star});
    const uid='psf'+Math.random().toString(36).slice(2, 8);
    const any=()=>!!(F.game || F.stat || F.side || F.band || F.star);
    function sel(id, label, all, items, val){
      return `<label class="psf-sel"><span class="sr">${esc(label)}</span><select id="${uid}-${id}" data-f="${id}" aria-label="${esc(label)}">`+
        `<option value="">${esc(all)}</option>${items.map(([v,l])=>`<option value="${esc(v)}"${String(v)===val? ' selected' : ''}>${esc(l)}</option>`).join('')}</select></label>`;
    }
    function draw(){
      el.innerHTML=`<div class="psf" role="group" aria-label="Filter picks">`+
        sel('game', 'Game', 'All games', opts.games, F.game)+
        sel('stat', 'Prop', 'All props', opts.stats, F.stat)+
        `<button type="button" class="chip psf-c" data-side="over" aria-pressed="${F.side==='over'}">Over</button>`+
        `<button type="button" class="chip psf-c" data-side="under" aria-pressed="${F.side==='under'}">Under</button>`+
        sel('band', 'Price', 'Any price', PRICE_BANDS.map(b=>[b[0], b[1]]), F.band)+
        `<button type="button" class="chip psf-c" data-star="1" aria-pressed="${F.star}"><span aria-hidden="true">★</span> Starred</button>`+
        (any()? `<button type="button" class="chip psf-c psf-clear" data-clear="1">✕ Clear</button>` : '')+`</div>`;
      el.querySelectorAll('select[data-f]').forEach(s=>s.onchange=()=>{ F[s.dataset.f]=s.value; changed(); });
      el.querySelectorAll('[data-side]').forEach(b=>b.onclick=()=>{ F.side= F.side===b.dataset.side? '' : b.dataset.side; changed(); });
      const st=el.querySelector('[data-star]'); if(st) st.onclick=()=>{ F.star=!F.star; changed(); };
      const cl=el.querySelector('[data-clear]'); if(cl) cl.onclick=()=>{ Object.assign(F, blank); changed(); };
    }
    function changed(){
      lsSet(KEY, F);
      const focus=document.activeElement && el.contains(document.activeElement)? (document.activeElement.dataset.f || document.activeElement.dataset.side || (document.activeElement.dataset.star && 'star')) : null;
      draw();
      if(focus){ const t=el.querySelector(`[data-f="${focus}"],[data-side="${focus}"]`) || (focus==='star' && el.querySelector('[data-star]')); if(t) t.focus({preventScroll:true}); }
      if(cfg.onChange) cfg.onChange(api.get());
    }
    function setOptions(o){
      opts={games:((o||{}).games||[]).map(x=>[String(x[0]), String(x[1])]), stats:((o||{}).stats||[]).map(x=>[String(x[0]), String(x[1])])};
      // a saved game or prop that isn't on today's board would hide everything
      if(F.game && !opts.games.some(g=>g[0]===F.game)) F.game='';
      if(F.stat && opts.stats.length && !opts.stats.some(s=>s[0]===F.stat)) F.stat='';
      draw();
    }
    const api={
      get(){ return Object.assign({}, F); },
      test(r){
        if(!r) return false;
        if(F.game && String(r.gid)!==F.game) return false;
        if(F.stat && String(r.sk)!==F.stat) return false;
        if(F.side && r.side!==F.side) return false;
        if(F.band){ const b=PRICE_BANDS.find(x=>x[0]===F.band), px=frac(r.price); if(!b || px==null || px<b[2] || px>=b[3]) return false; }
        if(F.star && !watch.has(r.sport||sport, r.pid)) return false;
        return true;
      },
      set(f){ Object.assign(F, blank, f||{}); changed(); },
      setOptions,
      clear(){ Object.assign(F, blank); changed(); }
    };
    if(el){ setOptions(cfg.options); if(cfg.sport || cfg.key) watch.onChange(()=>{ if(F.star && el.isConnected && cfg.onChange) cfg.onChange(api.get()); }); }
    return api;
  }

  // ---- line ladder: every listed line of one player's prop. rows: [{line, side, prob, pp, kp, vn, pd, kd, edge, listed}]
  // (prices as fractions or cents; pd/kd the dollars offered near pp/kp, under $25 = thin; edge in points or as a
  // fraction, or left out to use the model minus the cheaper price you can get; listed: the pick's lists, e.g. "TV").
  // o: {statText, open(row)}. The best edge is highlighted; tapping a row calls open(row). ----
  function lineLadder(el, rows, o){
    if(!el) return;
    o=o||{};
    rows=(rows||[]).filter(r=>r && r.line!=null).slice().sort((a,b)=>(+a.line- +b.line) || String(a.side).localeCompare(String(b.side)));
    if(!rows.length){ el.innerHTML=`<p class="mktnote">No listed lines for this prop right now.</p>`; return; }
    const thin=d=> d!=null && +d<25;
    const info=rows.map(r=>{
      const prob=frac(r.prob), pp=frac(r.pp), kp=frac(r.kp);
      const can=[pp!=null && !thin(r.pd)? pp : null, kp!=null && !thin(r.kd)? kp : null].filter(x=>x!=null);
      let edge=r.edge!=null && isFinite(+r.edge)? (Math.abs(+r.edge)<=1? +r.edge*100 : +r.edge) : (prob!=null && can.length? (prob-Math.min(...can))*100 : null);
      return {r, prob, pp, kp, edge:edge==null? null : Math.round(edge)};
    });
    const best=info.reduce((m,x)=> x.edge!=null && x.edge>0 && (m==null || x.edge>m.edge)? x : m, null);
    const cell=(name, v, d, on)=> v==null? `<span class="psl-px none">—</span>`
      : name==='P' && thin(d)? `<span class="psl-px thin" title="Less than $25 is offered near this price on Polymarket">thin</span>`
      : `<span class="psl-px${on? ' on' : ''}${thin(d)? ' thin' : ''}">${Math.round(v*100)}¢${thin(d)? '<i>thin</i>' : ''}</span>`;
    el.innerHTML=`<div class="psl" role="table" aria-label="${esc((o.statText||'Prop')+': every listed line')}">`+
      `<div class="psl-hd" role="row"><span role="columnheader">Line</span><span role="columnheader">Model</span><span role="columnheader" title="Polymarket"><span class="psl-lg">Polymarket</span><span class="psl-sm" aria-hidden="true">Poly</span></span><span role="columnheader">Kalshi</span><span role="columnheader">Edge</span></div>`+
      info.map((x,i)=>`<button type="button" class="psl-row${x===best? ' best' : ''}" role="row" data-i="${i}">`+
        `<span class="psl-line" role="cell"><span class="leantag ${esc(x.r.side)}">${esc(x.r.side)}</span> <b>${esc(x.r.line)}</b>${listTags(x.r.listed)}${x===best? '<span class="pst-tag best">best edge</span>' : ''}</span>`+
        `<span class="psl-pr" role="cell">${x.prob!=null? Math.round(x.prob*100)+'%' : '—'}</span>`+
        `<span role="cell">${cell('P', x.pp, x.r.pd, x.r.vn!=='K' && x.pp!=null)}</span>`+
        `<span role="cell">${cell('K', x.kp, x.r.kd, x.r.vn==='K')}</span>`+
        `<span class="psl-ed ${x.edge==null? '' : x.edge>=0? 'pos' : 'neg'}" role="cell">${x.edge==null? '—' : (x.edge>=0? '+' : '−')+Math.abs(x.edge)}</span></button>`).join('')+
      `</div><p class="psl-note">${esc(o.statText||'')} · edge = model chance minus the cheaper price with $25+ offered, in points. “thin” = under $25 offered near that price. Research, not betting advice.</p>`;
    el.querySelectorAll('.psl-row').forEach(b=>b.onclick=()=>{ if(o.open) o.open(info[+b.dataset.i].r); });
  }

  // ---- exact-market links: a page's DB.links (the builders' depth.exchange_links) -> {P, K} URLs for one game
  // and prop, null where unknown (the sheet then links the exchange's home page). ----
  function exchangeUrls(links, gid, stat){
    const g=links && gid!=null? links[String(gid)] : null, out={P:null, K:null};
    if(!g) return out;
    if(g.p && /^[a-z0-9-]+$/.test(g.p)) out.P='https://polymarket.us/event/'+g.p;
    const ev=g.k && stat!=null? g.k[String(stat)] : null;
    if(ev && /^[A-Za-z0-9]+-[A-Za-z0-9]+$/.test(ev)){ const s=ev.split('-')[0].toLowerCase(); out.K='https://kalshi.com/markets/'+s+'/props/'+ev.toLowerCase(); }
    return out;
  }

  // ---- bet calculator: one prop at the price you type. cfg.getPick() -> {prob, lo, hi, price, name, statText, side, line} or null.
  // The price box starts at the pick's price (fraction or cents) and keeps what you type until the pick changes.
  // Returns {refresh()}: call it when the page's current pick changes. ----
  function betCalc(el, cfg){
    if(!el) return {refresh(){}};
    cfg=cfg||{};
    const uid='psc'+Math.random().toString(36).slice(2, 8);
    let sig=null;
    function refresh(){
      let p=null; try{ p=cfg.getPick && cfg.getPick(); }catch(e){ p=null; }
      if(!p || p.prob==null){ sig=null; el.innerHTML=`<p class="mktnote">Pick a player, a prop and a line to price it here.</p>`; return; }
      const s=[p.name, p.statText, p.side, p.line].join('|'), inp=el.querySelector('.psc-in');
      const keep= s===sig && inp? inp.value : (frac(p.price)!=null? String(Math.round(frac(p.price)*100)) : '');
      sig=s;
      el.innerHTML=`<div class="psc">`+
        `<p class="psc-what">${p.name? `<b>${esc(p.name)}</b> · ` : ''}<span class="leantag ${esc(p.side)}">${esc(p.side)} ${esc(p.line)}</span> ${esc(p.statText)}</p>`+
        `<div class="psc-row"><label for="${uid}">Your price</label><span class="psc-box"><input class="psc-in" id="${uid}" type="number" inputmode="numeric" min="1" max="99" step="1" value="${esc(keep)}" placeholder="45"><span aria-hidden="true">¢</span></span>`+
        `<span class="mktmuted">what you'd pay for this side on Polymarket or Kalshi</span></div><div class="psc-out" aria-live="polite"></div></div>`;
      el.querySelector('.psc-in').addEventListener('input', ()=>out(p));
      out(p);
    }
    function out(p){
      const box=el.querySelector('.psc-out'), c=parseFloat(el.querySelector('.psc-in').value), prob=frac(p.prob);
      const lo=frac(p.lo), hi=frac(p.hi), range=lo!=null && hi!=null? ` (range ${Math.round(lo*100)}–${Math.round(hi*100)}%)` : '';
      if(!(isFinite(c) && c>=1 && c<=99)){
        box.innerHTML=`<p class="mktnote">Model chance for this side: <b>${pctTxt(prob)}</b>${range}. Type the price you see, in cents, for the payout, the edge and a stake guide.</p>`; return;
      }
      const price=c/100, mult=1/price, edge=prob-price, ev=prob*mult-1, b=mult-1, qk=Math.max(0, (prob*b-(1-prob))/b)/4;
      const conf= lo!=null && lo>price? 'Even the low end of the model range is above this price.' : hi!=null && hi<price? 'Even the high end of the model range is below this price: the market disagrees with the history.' : lo!=null? 'The price sits inside the model range: no clear edge either way.' : '';
      box.innerHTML=`<div class="pst-sum">`+
        `<div><span class="lab">Pays</span><b>${multTxt(mult)}</b><span class="sub">$10 returns $${(10*mult).toFixed(2)}</span></div>`+
        `<div><span class="lab">Model chance</span><b>${pctTxt(prob)}</b><span class="sub">price implies ${Math.round(c)}%</span></div>`+
        `<div><span class="lab">Edge</span><b class="${edge>=0? 'pos' : 'neg'}">${edge>=0? '+' : '−'}${Math.abs(Math.round(edge*100))}</b><span class="sub">points over the price</span></div>`+
        `<div><span class="lab">Expected return</span><b class="${ev>=0? 'pos' : 'neg'}">${ev>=0? '+' : '−'}${Math.abs(Math.round(ev*100))}¢</b><span class="sub">per $1 · ¼-Kelly ${(qk*100).toFixed(1)}% of bankroll</span></div>`+
        `</div><p class="mktnote psc-fine">${conf} Edge = model chance minus the price; expected return = chance × payout − 1. Kelly sizing assumes the model is right, and it isn't always, so a quarter of it is shown. Research, not betting advice.</p>`;
    }
    refresh();
    return {refresh};
  }

  // ---- parlay slip (any sport): your own legs, saved per sport on this device (psl_slip_<sport>).
  // cfg: {sport, getCurrent() -> leg or null (the prop on screen), legsFor(legs) -> the same legs with today's
  // prob/price (optional; matched by key, a missing one keeps its saved numbers), open(leg) (optional)}.
  // leg: {key, gid, pid, name, statText, side, line, prob, price}. Each leg's price is editable.
  // Returns {add(leg), refresh(), clear(), legs()}. ----
  const SLIP_MAX=12;
  function parlaySlip(el, cfg){
    cfg=cfg||{};
    const KEY='psl_slip_'+String(cfg.sport||'x');
    let legs=(lsGet(KEY, [])||[]).filter(l=>l && l.key!=null);
    const save=()=>lsSet(KEY, legs);
    const clean=l=>({key:String(l.key), gid:l.gid==null? '' : String(l.gid), pid:l.pid==null? '' : String(l.pid), name:String(l.name||''),
      statText:String(l.statText||''), side:l.side==='under'? 'under' : 'over', line:l.line, prob:frac(l.prob), price:frac(l.price), my:l.my!=null? +l.my : null});
    legs=legs.map(clean);
    function sync(){
      if(typeof cfg.legsFor!=='function' || !legs.length) return;
      let fresh=[]; try{ fresh=cfg.legsFor(legs.map(l=>Object.assign({}, l)))||[]; }catch(e){ fresh=[]; }
      const by={}; fresh.forEach(f=>{ if(f && f.key!=null) by[String(f.key)]=f; });
      legs.forEach(l=>{ const f=by[l.key]; if(!f) return; if(f.prob!=null) l.prob=frac(f.prob); if(f.price!==undefined) l.price=frac(f.price); });
      save();
    }
    function add(leg){
      if(!leg || leg.key==null){ toast('Pick a player, a prop and a line first'); return false; }
      const l=clean(leg);
      if(legs.some(x=>x.key===l.key)){ toast('That prop is already in your slip'); return false; }
      if(legs.length>=SLIP_MAX){ toast(`A slip holds up to ${SLIP_MAX} legs`); return false; }
      legs.push(l); save(); draw(); toast('Added to your parlay slip'); return true;
    }
    const legPx=l=> l.my!=null && l.my>=1 && l.my<=99? l.my/100 : l.price;
    function sumHtml(){
      if(!legs.length) return '';
      const probs=legs.map(l=>l.prob), pxs=legs.map(legPx), allP=probs.every(p=>p!=null), allX=pxs.every(x=>x!=null && x>0);
      const chance=allP? probs.reduce((a,b)=>a*b, 1) : null, pay=allX? pxs.reduce((a,x)=>a/x, 1) : null, ev=chance!=null && pay!=null? chance*pay-1 : null;
      const g={}; legs.forEach(l=>{ if(l.gid) g[l.gid]=(g[l.gid]||0)+1; });
      const same=Object.values(g).filter(n=>n>1).reduce((a,n)=>a+n, 0);
      return `<div class="pst-sum">`+
        `<div><span class="lab">Model chance</span><b>${chance!=null? pctTxt(chance) : '—'}</b><span class="sub">all ${legs.length} leg${legs.length>1? 's' : ''} hit</span></div>`+
        `<div><span class="lab">Pays</span><b>${pay!=null? multTxt(pay) : '—'}</b><span class="sub">${pay!=null? `$10 returns $${(10*pay).toFixed(2)}` : 'type every price'}</span></div>`+
        `<div><span class="lab">Fair payout</span><b>${chance? multTxt(1/chance) : '—'}</b><span class="sub">break-even for that chance</span></div>`+
        `<div><span class="lab">Expected return</span><b class="${ev==null? '' : ev>=0? 'pos' : 'neg'}">${ev!=null? (ev>=0? '+' : '−')+Math.abs(Math.round(ev*100))+'¢' : '—'}</b><span class="sub">per $1, at your prices</span></div>`+
        `</div>`+
        (same? `<div class="pst-warn" role="note"><b>${same} legs come from the same game.</b> Props in one game move together (a quarterback's yards and his receiver's, a scorer's points and his team's total), so the chance above, which treats the legs as independent, is not reliable for them. Read it as a rough guide.</div>` : '');
    }
    function draw(){
      if(!el) return;
      let cur=null; try{ cur=cfg.getCurrent && cfg.getCurrent(); }catch(e){ cur=null; }
      const curIn= cur && cur.key!=null && legs.some(l=>l.key===String(cur.key));
      el.innerHTML=`<div class="pss">`+
        `<div class="pss-top"><button type="button" class="btn pss-add"${!cur || curIn? ' disabled' : ''}>${curIn? '✓ In your slip' : '＋ Add current pick'}</button>`+
          (cur && !curIn? `<span class="pss-cur">${esc(cur.name)} <span class="leantag ${esc(cur.side)}">${esc(cur.side)}</span> ${esc(cur.line)} ${esc(cur.statText)}</span>` : !cur? `<span class="mktmuted">Open a player's prop to add it.</span>` : '')+`</div>`+
        (legs.length
          ? `<ol class="pss-legs">${legs.map((l,i)=>`<li class="pss-leg"><button type="button" class="pss-who" data-i="${i}"${cfg.open? '' : ' disabled'}><b>${esc(l.name)}</b> <span class="leantag ${esc(l.side)}">${esc(l.side)}</span> ${esc(l.line)} ${esc(l.statText)}</button>`+
              `<span class="pss-pr">${l.prob!=null? Math.round(l.prob*100)+'%' : '—'}<small>model</small></span>`+
              `<label class="pss-px"><span class="sr">Your price for ${esc(l.name)}, cents</span><input type="number" inputmode="numeric" min="1" max="99" step="1" data-i="${i}" value="${esc(l.my!=null? l.my : l.price!=null? Math.round(l.price*100) : '')}" placeholder="¢"><span aria-hidden="true">¢</span></label>`+
              `<button type="button" class="pss-rm" data-i="${i}" aria-label="Remove ${esc(l.name)} ${esc(l.statText)}">✕</button></li>`).join('')}</ol>`+
            `<div class="pss-sum" aria-live="polite">${sumHtml()}</div>`+
            `<div class="pss-foot"><button type="button" class="btn ghost pss-clear">Clear slip</button></div>`+
            `<p class="mktnote pss-fine">The chance multiplies each leg's model chance, which treats the legs as independent; the payout multiplies 1 / each price, starting from the live price (edit any of them to what you see). Research, not betting advice.</p>`
          : `<p class="mktnote">Your slip is empty. Open any prop and tap <b>＋ Add current pick</b> to build a parlay: you'll see the model's chance that every leg hits and the payout at your prices. Saved on this device.</p>`)+
        `</div>`;
      const ab=el.querySelector('.pss-add'); if(ab) ab.onclick=()=>{ let c=null; try{ c=cfg.getCurrent && cfg.getCurrent(); }catch(e){} add(c); };
      el.querySelectorAll('.pss-rm').forEach(b=>b.onclick=()=>{ legs.splice(+b.dataset.i, 1); save(); draw(); });
      el.querySelectorAll('.pss-px input').forEach(inp=>inp.addEventListener('input', ()=>{
        const v=parseFloat(inp.value), l=legs[+inp.dataset.i]; if(!l) return;
        l.my= isFinite(v) && v>=1 && v<=99? Math.round(v) : null; save();
        const s=el.querySelector('.pss-sum'); if(s) s.innerHTML=sumHtml(); }));
      el.querySelectorAll('.pss-who').forEach(b=>b.onclick=()=>{ const l=legs[+b.dataset.i]; if(l && cfg.open) cfg.open(Object.assign({}, l)); });
      const cb=el.querySelector('.pss-clear'); if(cb) cb.onclick=()=>{ legs=[]; save(); draw(); };
    }
    sync(); draw();
    return {add, refresh(){ sync(); draw(); }, clear(){ legs=[]; save(); draw(); }, legs(){ return legs.map(l=>Object.assign({}, l)); }};
  }

  return {teamVars, parlaySearch, parlayFinder, ticker, until, skeleton, esc, hashFor, pickHash, parsePickHash, syncHash, sharePick, toast, helpBtn, spark, verdict, icon, sheet, closeSheet, pickSheet, relatedPicks,
          isTracked, toggleBet, renderBets, loadBets, fairOf, setFair, probRing, pxMove, pxSpark, valueBanner, gameStrip, lockBadge, lockRibbon, lockNote, startLabel, gameTime, liveUS, venues, venueName, thinPrice, cap, capPick, thinOut, getView, setView,
          watch, starBtn, renderWatchlist, filterBar, lineLadder, exchangeUrls, betCalc, parlaySlip};
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
// pages and paused while hidden; affiliates are paid per "new". "ref/<code>/stay/<mark>" times the
// visit (below). Only the code is sent: no ID, no cookie. team_stats.py reads these (REF_RE, STAY_RE). Runs before the block below, which marks the browser
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
  // Time on site from an affiliate link: "ref/<code>/stay/<mark>" once this visit (this tab, across pages,
  // paused while hidden) reaches each mark, "0s" on arrival. The team dashboard turns the marks into an
  // average time on site per affiliate. MARKS must match STAY_MARKS in team_stats.py.
  (function(){
    const MARKS = [[0,'0s'],[10,'10s'],[20,'20s'],[60,'1m'],[180,'3m'],[600,'10m'],[1800,'30m']], TKEY = 'psl_ref_t';
    let t = null;
    try { t = JSON.parse(sessionStorage.getItem(TKEY) || 'null'); } catch(e) {}
    if (/^[a-z0-9-]{2,24}$/.test(code) && (!t || t.c !== code)) t = {c: code, ms: 0, k: 0};   // k: marks sent so far
    if (!t || !/^[a-z0-9-]{2,24}$/.test(t.c || '') || !(t.k < MARKS.length)) return;
    let since = 0, timer = 0;
    function keep(){ try { sessionStorage.setItem(TKEY, JSON.stringify(t)); } catch(e) {} }
    function tick(){
      const ms = t.ms + (since ? Date.now() - since : 0);
      while (t.k < MARKS.length && ms >= MARKS[t.k][0] * 1000) {
        count('ref/' + t.c + '/stay/' + MARKS[t.k][1], 'Affiliate visitor stayed ' + MARKS[t.k][1] + ': ' + t.c); t.k++;
      }
      keep(); clearTimeout(timer);
      if (since && t.k < MARKS.length) timer = setTimeout(tick, MARKS[t.k][0] * 1000 - ms + 50);
    }
    function on(){ if (since) return; since = Date.now(); tick(); }
    function off(){ if (!since) return; t.ms += Date.now() - since; since = 0; clearTimeout(timer); keep(); }
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') off(); else on(); });
    addEventListener('pagehide', off);
    addEventListener('pageshow', e => { if (e.persisted && document.visibilityState === 'visible') on(); });
    tick();
    if (document.visibilityState === 'visible') on();
  })();
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
// first page it also sends "visitor/new" or "visitor/returning" (VISITOR_RE), and a returning visitor sends
// "days/<range>" (DAYS_RE): how many different days this browser has visited, as 2, 3-4, 5-9 or 10+.
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
  let kind = null, range = null;
  if (n === 1) {
    kind = 'new';
    try { const first = localStorage.getItem('psl_first'); if (first && first !== day) kind = 'returning'; if (!first) localStorage.setItem('psl_first', day); } catch(e) {}
    // how many different days this browser has been here (a returning visitor from before this count began starts at 2)
    try {
      const prev = parseInt(localStorage.getItem('psl_days') || '0', 10) || 0;
      const days = kind === 'returning' ? Math.max(prev, 1) + 1 : 1;
      localStorage.setItem('psl_days', String(days));
      if (kind === 'returning') range = days >= 10 ? '10+' : days >= 5 ? '5-9' : days >= 3 ? '3-4' : '2';
    } catch(e) {}
  }
  let tries = 0;
  (function send(){
    const gc = window.goatcounter;
    if (gc && typeof gc.count === 'function') {
      gc.count({path: 'view/' + n, title: 'Page view ' + n + ' today', event: true});
      if (kind) gc.count({path: 'visitor/' + kind, title: (kind === 'new' ? 'New' : 'Returning') + ' visitor', event: true});
      if (range) gc.count({path: 'days/' + range, title: 'Returning visitor, ' + range + ' days', event: true});
    } else if (++tries < 40) setTimeout(send, 250);   // count.js loads async; give up after 10 s (blocked)
  })();
})();

// ---- outbound clicks: one anonymous GoatCounter event per click on a link that leaves the site,
// e.g. "click/polymarket-site/nfl" (what was clicked, then which page). No ID or cookie.
// team_stats.py reads these for the team dashboard and keeps them out of the visit counts.
(function(){
  const PAGE = (location.pathname.match(/\/(nfl|nba|nhl|mlb|tennis)\.html$/) || [])[1] || 'home';
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

// ---- offline app: sw.js keeps the last good copy of each page and data file for when the network is down ----
// Pages and data always come from the network when it answers; a saved copy is only used when it doesn't,
// and then this bar says so ("Offline: showing data from ..."). Not on the team dashboard.
// ?nosw on any page removes the worker and its caches from this browser (sw.js has a site-wide KILL switch).
(function(){
  const sw = navigator.serviceWorker;
  if (!sw || location.pathname.startsWith('/team/')) return;
  if (!(location.protocol === 'https:' || /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname))) return;
  if (/[?&]nosw\b/.test(location.search)) {
    if (sw.controller) sw.controller.postMessage({type: 'nosw'});   // stops it answering this page's requests too
    sw.getRegistrations().then(rs => rs.forEach(r => r.unregister())).catch(() => {});
    if (window.caches) caches.keys().then(ks => ks.forEach(k => k.startsWith('psl-') && caches.delete(k))).catch(() => {});
    return;
  }
  function bar(when){
    if (document.getElementById('psoffline')) return;
    const d = when ? new Date(when) : null, ok = d && !isNaN(d);
    const sameDay = ok && d.toDateString() === new Date().toDateString();
    const t = ok ? d.toLocaleString([], sameDay ? {hour:'numeric', minute:'2-digit'} : {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'}) : '';
    const b = document.createElement('div');
    b.id = 'psoffline'; b.setAttribute('role', 'status');
    b.style.cssText = 'position:fixed;left:50%;bottom:12px;transform:translateX(-50%);z-index:9999;max-width:calc(100% - 32px);display:flex;align-items:center;gap:10px;' +
      'padding:8px 10px 8px 14px;border-radius:999px;background:#241a0e;border:1px solid #6a5326;color:#f6ecd9;font:500 13.5px/1.3 var(--ps-body,system-ui,sans-serif);box-shadow:0 6px 20px rgba(0,0,0,.35)';
    b.innerHTML = `<span>${navigator.onLine ? 'No connection to the site' : 'Offline'}: showing data from ${t || 'your last visit'}. Prices may have moved.</span>` +
      '<button type="button" style="flex:none;border:0;border-radius:999px;padding:6px 12px;background:#e8b54a;color:#241a0e;font-family:inherit;font-weight:700;font-size:13px;line-height:1;cursor:pointer">Retry</button>';
    b.querySelector('button').onclick = () => location.reload();
    (document.body || document.documentElement).appendChild(b);
  }
  sw.addEventListener('message', e => { if (e.data && e.data.type === 'psl-offline') bar(e.data.when); });
  sw.startMessages && sw.startMessages();
  addEventListener('load', () => {
    sw.register('/sw.js').catch(() => {});
    // was this page itself the saved copy? (the worker can't message a page before it exists, so ask)
    const url = location.href.split('#')[0];
    if (sw.controller) sw.controller.postMessage({type: 'status', url});
    else sw.ready.then(r => r.active && r.active.postMessage({type: 'status', url, save: true}));   // first visit: loaded before the worker
  });
})();
