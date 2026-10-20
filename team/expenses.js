/* Prop Streak Lab team dashboard: the Expenses section.
   The list is shared by the team: encrypted in the browser with the team password (the same
   OpenSSL "Salted__" / PBKDF2-SHA256 600k / AES-256-CBC format as stats.enc) and saved as
   expenses.enc on the repo's `team-data` branch through the GitHub API. Anyone can read the
   encrypted file; only the team password opens it. Saving needs a GitHub token from someone with
   write access to the repo, kept in that browser only (localStorage). The `team-data` branch holds
   nothing else, so these commits never touch main or the update bot.
   index.html sends the password with a "psa-unlock" event and clears it with "psa-lock".
   window.psaTeamData shares the same storage with the rest of the dashboard (the Affiliates tab
   keeps affiliates.enc next to expenses.enc). */
(function(){
  const REPO = 'Brandon12344556677/FootballPropsFinal', BRANCH = 'team-data', PATH = 'expenses.enc';
  const apiFor = path => `https://api.github.com/repos/${REPO}/contents/${path}`;
  const ITERATIONS = 600000;   // must match index.html and team_stats.py
  const TOKEN_KEY = 'psa-gh-token';
  const CATS = {expense: ['Advertising', 'Software & web', 'Filing & legal', 'Equipment', 'Other'],
                income: ['Gift', 'Referral payout', 'Sponsorship', 'Other']};
  const WHO = ['Business account', 'Brandon', 'Max'];
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = n => (n < 0 ? '−' : '') + '$' + Math.abs(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const today = () => new Date().toLocaleDateString('en-CA');

  let pw = null, data = {v: 1, items: []}, sha = null, loaded = false, busy = false, login = null;
  let editing = null;   // {kind: 'item' | 'rec', id} while the form edits a saved entry

  // ---------- crypto (OpenSSL-compatible) ----------
  async function keyIv(pass, salt){
    const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveBits']);
    const bits = new Uint8Array(await crypto.subtle.deriveBits({name: 'PBKDF2', salt, iterations: ITERATIONS, hash: 'SHA-256'}, base, 384));
    return {key: await crypto.subtle.importKey('raw', bits.slice(0, 32), 'AES-CBC', false, ['encrypt', 'decrypt']), iv: bits.slice(32, 48)};
  }
  const b64 = u8 => { let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s); };
  const unb64 = s => Uint8Array.from(atob(s.replace(/\s+/g, '')), c => c.charCodeAt(0));
  async function encrypt(obj, pass){
    const salt = crypto.getRandomValues(new Uint8Array(8)), {key, iv} = await keyIv(pass, salt);
    const ct = new Uint8Array(await crypto.subtle.encrypt({name: 'AES-CBC', iv}, key, new TextEncoder().encode(JSON.stringify(obj))));
    const out = new Uint8Array(16 + ct.length); out.set(new TextEncoder().encode('Salted__')); out.set(salt, 8); out.set(ct, 16);
    return b64(out);
  }
  async function decrypt(text, pass){
    const raw = unb64(text);
    if (new TextDecoder().decode(raw.slice(0, 8)) !== 'Salted__') throw new Error('format');
    const {key, iv} = await keyIv(pass, raw.slice(8, 16));
    return JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({name: 'AES-CBC', iv}, key, raw.slice(16))));
  }

  // ---------- GitHub storage ----------
  function token(){ try { return localStorage.getItem(TOKEN_KEY) || ''; } catch(e){ return ''; } }
  function headers(){ const h = {Accept: 'application/vnd.github+json'}; const t = token(); if (t) h.Authorization = 'Bearer ' + t; return h; }
  async function fetchList(path = PATH){
    const r = await fetch(`${apiFor(path)}?ref=${BRANCH}&t=${Date.now()}`, {headers: headers(), cache: 'no-store'});
    if (r.status === 404) return {doc: {v: 1, items: []}, sha: null};
    if (!r.ok) throw Object.assign(new Error('read'), {status: r.status});
    const j = await r.json();
    return {doc: await decrypt(new TextDecoder().decode(unb64(j.content)), pw), sha: j.sha};
  }
  async function saveList(doc, prevSha, path = PATH){
    const body = {message: 'Update team data', branch: BRANCH, content: b64(new TextEncoder().encode(await encrypt(doc, pw)))};
    if (prevSha) body.sha = prevSha;
    const r = await fetch(apiFor(path), {method: 'PUT', headers: Object.assign({'Content-Type': 'application/json'}, headers()), body: JSON.stringify(body)});
    if (!r.ok) throw Object.assign(new Error('save'), {status: r.status});
    return (await r.json()).content.sha;
  }
  // Change a list: re-read the latest copy first, so two people saving don't overwrite each other.
  async function update(path, fn){
    for (let tries = 0; ; tries++){
      const cur = await fetchList(path);
      const doc = fn(JSON.parse(JSON.stringify(cur.doc)));
      try { return {doc, sha: await saveList(doc, cur.sha, path)}; }
      catch(e){ if (e.status !== 409 && e.status !== 422 || tries === 2) throw e; }   // someone saved in between: retry on top of theirs
    }
  }
  async function change(fn){
    if (busy) return;
    if (!token()) { msg('Connect GitHub below to save changes.', true); return; }
    busy = true; msg('Saving…');
    try {
      const r = await update(PATH, fn); sha = r.sha; data = r.doc;
      msg('Saved. Your teammate sees it on their next refresh.');
      render();
    } catch(e){
      msg(e.status === 401 ? 'GitHub rejected the token. Make a new one (steps below).' :
          e.status === 403 || e.status === 404 ? 'This GitHub account can’t write to the repo. Use an account Brandon added as a collaborator.' :
          'Couldn’t save. Check your connection and try again.', true);
    } finally { busy = false; }
  }

  // ---------- page ----------
  // ---- repeating charges: saved once in doc.recurring, counted on every date they fall on up to today ----
  const FREQ = {daily: 'every day', weekly: 'every week', monthly: 'every month', yearly: 'every year'};
  function nextDate(iso, freq, n){       // the n-th occurrence after iso (monthly/yearly keep the day, clamped to month end)
    const [y, m, d] = iso.split('-').map(Number);
    if (freq === 'daily' || freq === 'weekly') return new Date(Date.UTC(y, m - 1, d + (freq === 'daily' ? 1 : 7) * n)).toISOString().slice(0, 10);
    const months = freq === 'yearly' ? 12 * n : n, t = new Date(Date.UTC(y, m - 1 + months, 1));
    const last = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth() + 1, 0)).getUTCDate();
    return new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), Math.min(d, last))).toISOString().slice(0, 10);
  }
  function occurrences(r, until){
    const out = [], stop = r.end && r.end < until ? r.end : until;
    for (let n = 0; n < 4000; n++){ const day = nextDate(r.start, r.freq, n); if (day > stop) break; out.push(day); }   // a daily charge: ~11 years
    return out;
  }
  function allItems(){
    const t = today(), extra = [];
    (data.recurring || []).forEach(r => occurrences(r, t).forEach(day =>
      extra.push({id: r.id + '@' + day, rid: r.id, date: day, type: r.type, cat: r.cat, desc: r.desc, amount: r.amount, by: r.by, added: r.added})));
    return (data.items || []).concat(extra);
  }
  function upcoming(r){ const t = today(); for (let n = 0; n < 4000; n++){ const day = nextDate(r.start, r.freq, n); if (day > t) return r.end && day > r.end ? null : day; } return null; }

  function msg(t, bad){ const m = $('exMsg'); if (m){ m.textContent = t; m.classList.toggle('bad', !!bad); } }
  function fillCats(){
    const type = $('exType').value, sel = $('exCat'), keep = sel.value;
    sel.innerHTML = CATS[type].map(c => `<option>${esc(c)}</option>`).join('');
    if (CATS[type].includes(keep)) sel.value = keep;
  }
  // A select gets a value even when it isn't one of its options (an entry saved with an older name).
  function setSel(sel, v){
    if (v && ![...sel.options].some(o => o.value === v)) sel.insertAdjacentHTML('beforeend', `<option>${esc(v)}</option>`);
    if (v) sel.value = v;
  }
  // ---- editing: the form above loads a saved entry; Save changes replaces it, keeping its id ----
  function startEdit(kind, id){
    const e = kind === 'rec' ? (data.recurring || []).find(r => r.id === id) : (data.items || []).find(i => i.id === id);
    if (!e) { msg('That entry is gone: someone may have deleted it.', true); return; }
    editing = {kind, id};
    $('exDate').value = (kind === 'rec' ? e.start : e.date) || today();
    $('exType').value = e.type; fillCats(); setSel($('exCat'), e.cat);
    $('exDesc').value = e.desc || ''; $('exAmt').value = (+e.amount || 0).toFixed(2);
    $('exBy').innerHTML = WHO.map(w => `<option>${esc(w)}</option>`).join(''); setSel($('exBy'), e.by);
    $('exRep').value = kind === 'rec' ? e.freq : ''; $('exRep').disabled = kind !== 'rec';
    $('exHead').textContent = kind === 'rec' ? 'Edit a repeating charge' : 'Edit an entry';
    $('exSave').textContent = 'Save changes'; $('exCancel').hidden = false;
    msg(kind === 'rec' ? 'Changes apply to every time it was counted, past ones too. To change only future charges, Stop it and add a new one.' : '');
    $('exPanel').scrollIntoView({behavior: 'smooth', block: 'start'}); $('exDesc').focus({preventScroll: true});
  }
  function endEdit(){
    editing = null;
    $('exHead').textContent = 'Add an expense or money in';
    $('exSave').textContent = 'Save'; $('exCancel').hidden = true; $('exRep').disabled = false;
    $('exDate').value = today(); $('exDesc').value = ''; $('exAmt').value = ''; $('exRep').value = '';
    $('exBy').innerHTML = WHO.map(w => `<option>${esc(w)}</option>`).join(''); fillCats();
  }
  function render(){
    if (!$('exPanel')) return;
    const items = allItems().sort((a, b) => (b.date || '').localeCompare(a.date || '') || (b.added || 0) - (a.added || 0));
    const out = items.filter(i => i.type === 'expense'), inn = items.filter(i => i.type === 'income');
    const sum = a => a.reduce((s, i) => s + (+i.amount || 0), 0);
    const month = today().slice(0, 7), mOut = sum(out.filter(i => (i.date || '').startsWith(month)));
    const tOut = sum(out), tIn = sum(inn);
    $('exKpis').innerHTML = [
      ['Spent this month', money(mOut), new Date().toLocaleDateString('en-US', {month: 'long', year: 'numeric'})],
      ['Spent in all', money(tOut), `${out.length} expense${out.length === 1 ? '' : 's'}`],
      ['Money in', money(tIn), `${inn.length} entr${inn.length === 1 ? 'y' : 'ies'} (gifts, payouts)`],
      ['Balance', money(tIn - tOut), 'money in minus spent']
    ].map(([l, v, s], i) => `<div class="kpi"><span class="label">${l}</span><span class="v sm${i === 3 ? (tIn - tOut >= 0 ? ' up' : ' down') : ''}">${v}</span><span class="s">${esc(s)}</span></div>`).join('');
    const byCat = {}; out.forEach(i => { byCat[i.cat] = (byCat[i.cat] || 0) + (+i.amount || 0); });
    const cats = Object.entries(byCat).sort((a, b) => b[1] - a[1]), top = cats.length ? cats[0][1] : 1;
    $('exCats').innerHTML = cats.length ? cats.map(([c, n]) =>
      `<li class="row"><span class="bar" style="width:${(100 * n / top).toFixed(1)}%"></span><span class="name">${esc(c)}</span><span class="pct">${tOut ? Math.round(100 * n / tOut) + '%' : ''}</span><span class="n">${money(n)}</span></li>`).join('')
      : '<li class="empty">No expenses yet.</li>';
    $('exRows').innerHTML = items.length ? items.map(i =>
      `<tr><td>${esc(i.date)}</td><td>${esc(i.desc)}<small>${esc(i.cat)}${i.by ? ' · ' + esc(i.by) : ''}</small></td>` +
      `<td class="n ${i.type === 'income' ? 'up' : ''}">${i.type === 'income' ? '+' : '−'}${money(+i.amount || 0).replace('−', '')}</td>` +
      `<td>${i.rid ? `<small class="exrep" title="A repeating charge: stop it in Repeating charges above">\u21bb ${esc(FREQ[(data.recurring.find(r => r.id === i.rid) || {}).freq] || 'repeats')}</small>` : `<span class="exacts"><button type="button" class="ghost exedit" data-id="${esc(i.id)}" aria-label="Edit ${esc(i.desc)}">Edit</button><button type="button" class="ghost exdel" data-id="${esc(i.id)}" aria-label="Delete ${esc(i.desc)}">Delete</button></span>`}</td></tr>`).join('')
      : `<tr><td colspan="4" class="empty">${loaded ? 'Nothing recorded yet. Add the first entry above.' : 'Loading…'}</td></tr>`;
    const rec = (data.recurring || []).slice().sort((a, b) => (a.end ? 1 : 0) - (b.end ? 1 : 0) || a.desc.localeCompare(b.desc));
    $('exRecWrap').hidden = !rec.length;
    $('exRec').innerHTML = rec.map(r => { const nx = upcoming(r), n = occurrences(r, today()).length;
      return `<li class="row"><span class="name">${esc(r.desc)} <small>${esc(r.cat)} · ${money(+r.amount || 0)} ${esc(FREQ[r.freq] || '')} since ${esc(r.start)}${r.end ? ' · stopped ' + esc(r.end) : nx ? ' · next ' + esc(nx) : ''}</small></span>` +
        `<span class="pct">${n}\u00d7</span><span class="n"><button type="button" class="ghost exredit" data-id="${esc(r.id)}">Edit</button> ${r.end ? '' : `<button type="button" class="ghost exstop" data-id="${esc(r.id)}">Stop</button> `}<button type="button" class="ghost exrdel" data-id="${esc(r.id)}" title="Remove it and every time it was counted">Delete</button></span></li>`; }).join('');
    const t = token();
    $('exConn').innerHTML = t
      ? `Saving as <b>${esc(login || 'your GitHub account')}</b> on this device. <button type="button" class="ghost" id="exDisc">Disconnect</button>`
      : 'Not connected on this device: you can see the list but not change it.';
    $('exTokWrap').hidden = !!t;
    const d = $('exDisc'); if (d) d.onclick = () => { try { localStorage.removeItem(TOKEN_KEY); } catch(e){} login = null; msg(''); render(); };
  }
  async function who(){
    if (!token()) { login = null; return; }
    try { const r = await fetch('https://api.github.com/user', {headers: headers()}); if (r.ok) login = (await r.json()).login; else if (r.status === 401) login = 'an expired token'; } catch(e){}
    render();
  }
  async function reload(){
    if (!pw) return;
    try { const r = await fetchList(); data = r.doc; sha = r.sha; loaded = true; render(); }
    catch(e){ loaded = true; msg(e.message === 'format' || e.name === 'OperationError' ? 'The saved list doesn’t open with this password.' : 'Couldn’t load the list. Refresh to try again.', true); render(); }
  }
  function csv(){
    const rows = [['Date', 'Type', 'Category', 'Description', 'Paid by / from', 'Amount']]
      .concat(allItems().sort((a, b) => (a.date || '').localeCompare(b.date || ''))
      .map(i => [i.date, i.type === 'income' ? 'Money in' : 'Expense', i.cat, i.desc, i.by, (i.type === 'income' ? '' : '-') + (+i.amount || 0).toFixed(2)]));
    const text = rows.map(r => r.map(v => /[",\n]/.test(String(v ?? '')) ? '"' + String(v).replace(/"/g, '""') + '"' : (v ?? '')).join(',')).join('\n');
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], {type: 'text/csv'}));
    a.download = `prop-streak-lab-expenses-${today()}.csv`; document.body.appendChild(a); a.click(); a.remove();
  }

  function wire(){
    if (!$('exPanel') || $('exPanel').dataset.wired) return; $('exPanel').dataset.wired = '1';
    $('exDate').value = today();
    $('exBy').innerHTML = WHO.map(w => `<option>${esc(w)}</option>`).join('');
    fillCats();
    $('exType').addEventListener('change', fillCats);
    $('exForm').addEventListener('submit', e => {
      e.preventDefault();
      const amount = Math.round(parseFloat(String($('exAmt').value).replace(/[$,]/g, '')) * 100) / 100;
      const desc = $('exDesc').value.trim();
      if (!(amount > 0)) { msg('Enter an amount above $0.', true); return; }
      if (!desc) { msg('Add a short description.', true); return; }
      const item = {id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), date: $('exDate').value || today(),
                    type: $('exType').value, cat: $('exCat').value, desc, amount, by: $('exBy').value, added: Date.now()};
      if (editing){   // replace the saved entry, keeping its id and when it was first added
        const {kind, id} = editing, fields = {type: item.type, cat: item.cat, desc, amount, by: item.by, edited: Date.now()};
        let found = false;
        change(doc => {
          if (kind === 'rec') {
            const freq = $('exRep').value || 'monthly';
            doc.recurring = (doc.recurring || []).map(r => r.id === id ? (found = true, Object.assign({}, r, fields, {start: item.date, freq})) : r);
          } else doc.items = (doc.items || []).map(i => i.id === id ? (found = true, Object.assign({}, i, fields, {date: item.date})) : i);
          return doc;
        }).then(() => {
          if ($('exMsg').classList.contains('bad')) return;
          if (!found) { msg('That entry is gone: someone may have deleted it. Nothing was changed.', true); return; }
          endEdit(); msg('Changes saved. Your teammate sees them on their next refresh.');
        });
        return;
      }
      const freq = $('exRep').value;
      if (freq){   // a repeating charge: saved once, counted on each date it falls on
        const r = {id: item.id, start: item.date, freq, type: item.type, cat: item.cat, desc, amount, by: item.by, added: item.added, end: null};
        change(doc => { (doc.recurring = doc.recurring || []).push(r); return doc; }).then(() => { if (!$('exMsg').classList.contains('bad')) { $('exDesc').value = ''; $('exAmt').value = ''; $('exRep').value = ''; } });
        return;
      }
      change(doc => { (doc.items = doc.items || []).push(item); return doc; }).then(() => { if (!$('exMsg').classList.contains('bad')) { $('exDesc').value = ''; $('exAmt').value = ''; } });
    });
    $('exCancel').addEventListener('click', () => { endEdit(); msg(''); });
    $('exRows').addEventListener('click', e => {
      const ed = e.target.closest('.exedit'); if (ed) { startEdit('item', ed.dataset.id); return; }
      const b = e.target.closest('.exdel'); if (!b) return;
      if (b.dataset.sure !== '1') { b.dataset.sure = '1'; b.textContent = 'Sure?'; setTimeout(() => { if (b.isConnected) { b.dataset.sure = ''; b.textContent = 'Delete'; } }, 3000); return; }
      const id = b.dataset.id;
      if (editing && editing.id === id) endEdit();
      change(doc => { doc.items = (doc.items || []).filter(i => i.id !== id); return doc; });
    });
    $('exRec').addEventListener('click', e => {
      const ed = e.target.closest('.exredit'); if (ed) { startEdit('rec', ed.dataset.id); return; }
      const b = e.target.closest('.exstop, .exrdel'); if (!b) return;
      if (b.dataset.sure !== '1') { b.dataset.sure = '1'; b.dataset.was = b.textContent; b.textContent = 'Sure?'; setTimeout(() => { if (b.isConnected) { b.dataset.sure = ''; b.textContent = b.dataset.was; } }, 3000); return; }
      const id = b.dataset.id, stop = b.classList.contains('exstop');
      change(doc => {
        doc.recurring = (doc.recurring || []);
        if (stop) doc.recurring.forEach(r => { if (r.id === id) r.end = today(); });   // keeps what was already charged
        else doc.recurring = doc.recurring.filter(r => r.id !== id);                    // removes it and its past charges
        return doc;
      });
    });
    $('exTokSave').addEventListener('click', () => {
      const t = $('exTok').value.trim(); if (!t) return;
      try { localStorage.setItem(TOKEN_KEY, t); } catch(e){ msg('This browser won’t store the token.', true); return; }
      $('exTok').value = ''; msg('Connected on this device.'); who(); render();
    });
    $('exCsv').addEventListener('click', csv);
  }

  // For other panels: read(path) → {v, items}, update(path, fn) → saved doc. Errors carry .status
  // (401 bad token, 403/404 no write access); a missing token throws {status: 0}.
  window.psaTeamData = {
    ready: () => !!pw,
    canSave: () => !!token(),
    read: async path => (await fetchList(path)).doc,
    update: async (path, fn) => { if (!token()) throw Object.assign(new Error('token'), {status: 0}); return (await update(path, fn)).doc; }
  };

  window.addEventListener('psa-unlock', e => { pw = e.detail && e.detail.pw; wire(); render(); reload(); who(); });
  window.addEventListener('psa-lock', () => { pw = null; data = {v: 1, items: []}; sha = null; loaded = false; });
  window.addEventListener('psa-refresh', () => { if (!busy) reload(); });
})();
