/* Prop Streak Lab — service worker: the installed app opens instantly and still works offline,
   without ever showing an old price to someone who is online.
   Registered from app.js (https or localhost, never on /team/).

   What it does with each request (same-origin GETs only; everything else goes straight to the network):
   - app.js/app.css and anything else with ?v=, plus /fonts/: cache first. A new ?v= is a new URL,
     so a changed file is always fetched fresh.
   - Pages (HTML) and data (.json): network first. The network answer is always the one used, and
     it is saved for later. Only when the network fails, or says nothing for TIMEOUT ms, does the
     saved copy come back (the page then shows "Offline: showing data from ..." from app.js).
     A page with no saved copy gets offline.html.
   - Other images, icons, fonts.css and the manifest: the saved copy at once, refreshed in the background.
   - Never: POST, other sites (Polymarket, Kalshi, ESPN, GoatCounter, Buttondown...), /team/ and
     anything a /team/ page asks for, a fetch with {cache:'no-store'}, sw.js.

   When app.js or app.css gets a new ?v=, change the SHELL line here too (test_sw.py checks it) and
   bump VERSION, which clears the old caches on the next visit.
   Kill switch: set KILL = true and deploy; every browser drops its caches and unregisters the
   worker on its next visit (to retire it for good, also drop the register call in app.js).
   Or open any page with ?nosw (app.js unregisters it for that browser). */
const VERSION = '20261117c';
const KILL = false;
const SHELL_CACHE = 'psl-shell-' + VERSION;   // the precached app shell + cache-first assets
const PAGES_CACHE = 'psl-pages-' + VERSION;   // last good copy of each page and data file
const TIMEOUT = 4000;                          // ms to wait for the network before using a saved page/data file
const MAX_PAGES = 120;                         // saved pages + data files kept (oldest dropped first)
const SHELL = [
  '/', '/offline.html',
  '/app.js?v=20261117c', '/app.css?v=20261117b',
  '/fonts.css', '/fonts/inter-latin-wght-normal.woff2', '/fonts/archivo-latin-wght-normal.woff2',
  '/favicon.ico', '/favicon.svg', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png',
  '/site.webmanifest',
];

self.addEventListener('install', e => {
  self.skipWaiting();
  if (KILL) return;
  // 'reload' skips the browser's HTTP cache, so the shell is the live copy
  e.waitUntil(caches.open(SHELL_CACHE).then(c => c.addAll(SHELL.map(u => new Request(u, {cache: 'reload'})))));
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keep = KILL ? [] : [SHELL_CACHE, PAGES_CACHE];
    for (const k of await caches.keys()) if (k.startsWith('psl-') && !keep.includes(k)) await caches.delete(k);
    // open pages keep working (this worker answers nothing) and load from the network next time;
    // app.js registering it again on each visit just repeats this, so no reload loop
    if (KILL) { await self.registration.unregister(); return; }
    await self.clients.claim();
  })());
});

// Pages served from the cache because the network failed: url -> the saved copy's Date header.
// The page asks about itself once it loads (a message can't reach a page that doesn't exist yet).
const fromCache = new Map();

let off = false;   // ?nosw: this browser asked for the worker to go (app.js)

self.addEventListener('message', e => {
  const m = e.data || {};
  if (m.type === 'nosw') {
    off = true;
    e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('psl-')).map(k => caches.delete(k))))
      .then(() => self.registration.unregister()));
    return;
  }
  if (m.type !== 'status' || !e.source || KILL || off) return;
  const when = fromCache.get(m.url);
  fromCache.delete(m.url);
  if (when !== undefined) e.source.postMessage({type: 'psl-offline', when});
  // the page that registered the worker was loaded before it took over: save it now
  if (m.save && handled(new URL(m.url)) === 'net') e.waitUntil(caches.open(PAGES_CACHE).then(async c => {
    if (!(await c.match(m.url))) { const r = await fetch(m.url).catch(() => null); if (savable(r)) await c.put(m.url, r); }
  }));
});

// 'cache' (cache first), 'net' (network first), 'swr' (saved copy, refreshed behind) or null (leave alone)
function handled(u) {
  if (u.origin !== self.location.origin) return null;
  const p = u.pathname;
  if (p.startsWith('/team/') || p === '/sw.js') return null;
  if (u.searchParams.has('v') || p.startsWith('/fonts/')) return 'cache';
  if (p.endsWith('/') || p.endsWith('.html') || p.endsWith('.json') || !/\.[a-z0-9]+$/i.test(p)) return 'net';
  if (/\.(css|js|png|svg|ico|jpg|jpeg|webp|gif|webmanifest)$/i.test(p)) return 'swr';
  return null;
}
// only plain, complete 200s from this site (a redirected answer can't be replayed for a page)
const savable = r => r && r.ok && r.status === 200 && r.type === 'basic' && !r.redirected;

self.addEventListener('fetch', e => {
  const req = e.request;
  if (KILL || off || req.method !== 'GET' || req.headers.has('range')) return;
  if (req.cache === 'no-store') return;   // the caller wants no saved copy (live prices, the team dashboard)
  // requests made by a team dashboard page (it shares this worker's scope) are left alone too
  if (req.referrer && new URL(req.referrer).pathname.startsWith('/team/')) return;
  const how = handled(new URL(req.url));
  if (how === 'cache') e.respondWith(cacheFirst(req));
  else if (how === 'swr') e.respondWith(staleWhileRevalidate(req, e));
  else if (how === 'net') e.respondWith(networkFirst(req, e));
});

async function cacheFirst(req) {
  const hit = await caches.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (savable(res)) { const c = await caches.open(SHELL_CACHE); await c.put(req, res.clone()); }
  return res;
}

async function staleWhileRevalidate(req, e) {
  const hit = await caches.match(req);
  const live = fetch(req).then(async res => {
    if (savable(res)) { const c = await caches.open(SHELL_CACHE); await c.put(req, res.clone()); }
    return res;
  });
  if (hit) { e.waitUntil(live.catch(() => {})); return hit; }
  return live;
}

async function networkFirst(req, e) {
  const nav = req.mode === 'navigate';
  const live = fetch(req).then(res => {
    if (savable(res)) e.waitUntil(save(req, res.clone()));
    return res;
  });
  e.waitUntil(live.catch(() => {}));
  // whichever comes first: the network's answer, a network error, or the timeout
  const first = await Promise.race([
    live.then(res => ({res}), () => ({failed: true})),
    new Promise(r => setTimeout(() => r({slow: true}), TIMEOUT)),
  ]);
  if (first.res) { fromCache.delete(req.url); return first.res; }   // the network answered: always use it
  const saved = await savedCopy(req, nav);
  if (saved) {
    const when = saved.headers.get('date') || '';
    if (nav) fromCache.set(req.url, when);
    else if (e.clientId) self.clients.get(e.clientId).then(c => c && c.postMessage({type: 'psl-offline', when}));
    return saved;
  }
  if (first.slow) return live.catch(() => offline(nav));   // nothing saved: keep waiting for the network
  return offline(nav);
}

async function savedCopy(req, nav) {
  const c = await caches.open(PAGES_CACHE);
  // a page link with ?ref= or the like still finds the plain page
  return (await c.match(req)) || (nav ? (await c.match(req, {ignoreSearch: true})) || (await caches.match(req)) : null);
}

async function offline(nav) {
  if (nav) { const page = await caches.match('/offline.html'); if (page) return page; }
  return Response.error();
}

async function save(req, res) {
  const c = await caches.open(PAGES_CACHE);
  await c.delete(req);   // re-adding moves it to the end, so the trim below drops the least recently used
  await c.put(req, res);
  const keys = await c.keys();
  for (const k of keys.slice(0, Math.max(0, keys.length - MAX_PAGES))) await c.delete(k);
}
