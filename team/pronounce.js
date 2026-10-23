/* Prop Streak Lab team dashboard: how to say each player's name, for the 3 Picks of the Day video.
   Looks the player up on English Wikipedia (its API allows browser requests) and reads the article's
   lead: a {{respell}} ("YOH-kitch") if there is one, else its English IPA ({{IPAc-en}}) turned into
   the same kind of respelling, else the native IPA ({{IPA|lang|...}}) as written; plus a recording when
   the article links one. "Hear it" has the browser's voice read the respelling (or the name). Cached in
   this browser for 30 days. Display only: nothing here changes a pick. */
(function(){
  const API = 'https://en.wikipedia.org/w/api.php?format=json&origin=*&';
  const SPORT = {nba: 'basketball', nhl: 'ice hockey', mlb: 'baseball', nfl: 'American football'};
  const CACHE = 'psa-say:', DAYS = 30;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const plain = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

  // {{IPAc-en}} takes ASCII stand-ins too (n|I|'|m|i|@|s): to IPA first
  const ASCII = {"'": 'ˈ', ',': 'ˌ', '@': 'ə', 'I': 'ɪ', 'E': 'ɛ', '{': 'æ', 'V': 'ʌ', 'Q': 'ɒ', 'U': 'ʊ', 'A:': 'ɑː', 'O:': 'ɔː',
    'i:': 'iː', 'u:': 'uː', 'eI': 'eɪ', 'aI': 'aɪ', 'OI': 'ɔɪ', 'oU': 'oʊ', 'aU': 'aʊ', '3:r': 'ɜːr', '@r': 'ər', 'S': 'ʃ',
    'Z': 'ʒ', 'T': 'θ', 'D': 'ð', 'N': 'ŋ', 'tS': 'tʃ', 'dZ': 'dʒ', 'g': 'ɡ'};
  // Wikipedia's pronunciation respelling key; [closed syllable, open syllable] where they differ
  const SOUND = {'æ': ['a', 'ah'], 'ɑː': 'ah', 'ɑ': 'ah', 'ɒ': ['o', 'ah'], 'ɔː': 'aw', 'ɔ': 'aw', 'eɪ': 'ay', 'ɛ': ['e', 'eh'],
    'iː': 'ee', 'i': 'ee', 'ɪ': ['i', 'ih'], 'aɪ': 'eye', 'oʊ': 'oh', 'ʊ': 'uu', 'uː': 'oo', 'u': 'oo', 'ʌ': ['u', 'uh'],
    'aʊ': 'ow', 'ɔɪ': 'oy', 'ə': 'ə', 'ər': 'ər', 'ɜːr': 'ur', 'ɪər': 'eer', 'ɛər': 'air', 'ʊər': 'oor', 'ɑːr': 'ar', 'ɔːr': 'or',
    'juː': 'ew', 'ɡ': 'g', 'j': 'y', 'ŋ': 'ng', 'θ': 'th', 'ð': 'dh', 'ʃ': 'sh', 'ʒ': 'zh', 'tʃ': 'ch', 'dʒ': 'j', 'x': 'kh', 'hw': 'wh'};
  const VOWEL = /[aeiouəæɑɒɔɛɪʊʌɜ]/;

  function fromIpacEn(parts){
    const words = [[]];
    let syl = null;
    const start = stress => { syl = {stress, s: []}; words[words.length - 1].push(syl); };
    for (let raw of parts){
      const t = ASCII[raw] || raw;
      if (t === '_' || t === ' '){ words.push([]); syl = null; continue; }
      if (t === 'ˈ' || t === 'ˌ' || t === '.' || t === '-'){ start(t === 'ˈ'); continue; }
      if (!syl) start(false);
      syl.s.push(t);
    }
    // the template often marks only the stress: split the rest by vowel ("KAYtə" -> "KAY-tə"), the
    // consonant before a second vowel opening the next syllable
    const split = s => {
      const out = [{stress: s.stress, s: []}];
      s.s.forEach((t, i) => {
        const cur = out[out.length - 1];
        if (VOWEL.test(t) && cur.s.some(x => VOWEL.test(x))){
          const prev = cur.s[cur.s.length - 1], next = {stress: false, s: []};
          if (prev && !VOWEL.test(prev) && cur.s.length > 1) next.s.push(cur.s.pop());
          out.push(next);
        }
        out[out.length - 1].s.push(t);
      });
      return out;
    };
    // a vowel ending its syllable takes the open spelling ("ih"), else the closed one ("i")
    const say = s => s.s.map((t, i) => { const v = SOUND[t] ?? t; return Array.isArray(v) ? v[i === s.s.length - 1 ? 1 : 0] : v; }).join('');
    return words.map(w => w.filter(s => s.s.length).flatMap(split)).filter(w => w.length)
      .map(w => w.map(s => s.stress ? say(s).toUpperCase().replace(/Ə/g, 'ə') : say(s)).join('-')).join(' ');
  }

  // {{template|a|b|c}} -> [name, [a, b, c]], the first match of any of names (nested templates dropped)
  function template(text, names){
    const re = new RegExp('\\{\\{\\s*(' + names + ')\\s*\\|([^{}]*)\\}\\}', 'i'), m = text.match(re);
    return m ? [m[1].toLowerCase(), m[2].split('|').map(s => s.trim())] : null;
  }

  function parse(text){
    text = text.replace(/<!--[\s\S]*?-->/g, '').replace(/<ref[\s\S]*?(<\/ref>|\/>)/g, '');
    const out = {};
    const rs = template(text, 'respell');
    if (rs) out.say = rs[1].filter(p => !p.includes('=')).map(p => p === '_' ? ' ' : p).join('-').replace(/-? -?/g, ' ');
    const en = template(text, 'IPAc-en');
    if (en){
      const parts = en[1].filter(p => !p.includes('=') && !/^(US|UK|pron|local|also|lang|audio)$/i.test(p));
      if (!out.say) out.say = fromIpacEn(parts);
      out.ipa = '/' + parts.map(p => ASCII[p] || p).join('').replace(/_/g, ' ') + '/';
    }
    const native = template(text, 'IPA(?:-[a-z-]+)?');   // {{IPA|pt|...}}, or the older {{IPA-pt|...}}
    if (native){
      const old = native[0].match(/^ipa-(.+)/), lang = old ? old[1] : native[1][0], ipa = old ? native[1][0] : native[1][1];
      if (ipa && !/^en/i.test(lang)){
        out.native = '[' + ipa.replace(/\s+/g, ' ').trim() + ']';
        out.lang = lang;
      }
    }
    const file = text.match(/([\w\-. ()]+\.(?:ogg|oga|mp3|wav|flac))/i);
    if (file) out.audio = 'https://commons.wikimedia.org/wiki/Special:FilePath/' + encodeURIComponent(file[1].trim());
    if (out.say) out.say = out.say.replace(/-+/g, '-').replace(/(^-|-$)/g, '');
    return out;
  }

  async function look(name, sport){
    const key = CACHE + plain(name) + ':' + sport;
    try { const c = JSON.parse(localStorage.getItem(key) || 'null'); if (c && Date.now() - c.t < DAYS * 864e5) return c.v; } catch(e){}
    const q = await fetch(API + 'action=query&list=search&srlimit=3&srsearch=' + encodeURIComponent(name + ' ' + (SPORT[sport] || ''))).then(r => r.json());
    const last = plain(name).split(/\s+/).pop();
    const hit = (q.query && q.query.search || []).find(x => plain(x.title).includes(last));   // the right person, not a namesake team page
    let v = {none: true};
    if (hit){
      const w = await fetch(API + 'action=parse&prop=wikitext&section=0&redirects=1&page=' + encodeURIComponent(hit.title)).then(r => r.json());
      v = Object.assign(parse((w.parse && w.parse.wikitext && w.parse.wikitext['*']) || ''), {page: 'https://en.wikipedia.org/wiki/' + encodeURIComponent(hit.title.replace(/ /g, '_'))});
      if (!v.say && !v.native && !v.audio) v.none = true;
    }
    try { localStorage.setItem(key, JSON.stringify({t: Date.now(), v})); } catch(e){}
    return v;
  }

  function speak(text){
    if (!window.speechSynthesis) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text.replace(/ə/g, 'uh').replace(/-/g, ''));   // the voice reads the respelling, not the spelling
    u.lang = 'en-US'; u.rate = 0.8;
    speechSynthesis.speak(u);
  }

  // Fill every [data-say] under root (data-say = the name, data-sport = nba/nhl/mlb/nfl)
  async function fill(root){
    if (!root) return;
    for (const el of root.querySelectorAll('[data-say]')){
      const name = el.dataset.say, sport = el.dataset.sport;
      el.innerHTML = '<span class="label">Say it</span> <span class="tp-say-v">Looking up…</span>';
      let v;
      try { v = await look(name, sport); } catch(e){ v = {none: true, err: true}; }
      const bits = [];
      if (v.say) bits.push(`<b>${esc(v.say)}</b>`);
      if (v.native) bits.push(`<span title="${esc(v.lang || '')} pronunciation">${esc(v.native)}</span>`);
      if (v.none) bits.push(v.err ? 'Couldn’t reach Wikipedia.' : 'No pronunciation guide on Wikipedia.');
      if (v.page) bits.push(`<a href="${esc(v.page)}" target="_blank" rel="noopener">Wikipedia</a>`);
      el.querySelector('.tp-say-v').innerHTML = bits.join(' · ') + ' ' +
        (window.speechSynthesis ? `<button class="ghost tp-say-btn" type="button">🔊 Hear it</button>` : '') +
        (v.audio ? ` <button class="ghost tp-say-rec" type="button">▶ Recording</button>` : '');
      const b = el.querySelector('.tp-say-btn'), r = el.querySelector('.tp-say-rec');
      if (b) b.addEventListener('click', () => speak(v.say || name));
      if (r) r.addEventListener('click', () => { new Audio(v.audio).play().catch(() => window.open(v.audio, '_blank', 'noopener')); });
    }
  }

  window.psaSay = {fill, parse, fromIpacEn};
})();
