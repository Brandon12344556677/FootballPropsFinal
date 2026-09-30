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
    const fresh=[...document.querySelectorAll('.pickcard .ring:not([data-w])')];
    fresh.forEach(r=>{ r.dataset.w='1'; if(io) io.observe(r); else r.classList.add('on'); });
    // Safety net for browsers/webviews where the observer never reports: fill whatever is on screen.
    if(fresh.length) setTimeout(()=>fresh.forEach(r=>{ if(r.classList.contains('on')) return;
      const b=r.getBoundingClientRect(); if(b.bottom>0 && b.top<innerHeight){ r.classList.add('on'); if(io) io.unobserve(r); } }), 1200);
  }
  let queued=false;
  new MutationObserver(()=>{ if(queued) return; queued=true; setTimeout(()=>{ queued=false; watchRings(); }, 60); })
    .observe(document.documentElement, {childList:true, subtree:true});

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

  return {teamVars, ticker, until, skeleton, esc, hashFor, pickHash, parsePickHash, syncHash, sharePick, toast};
})();
