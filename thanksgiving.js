/* Prop Streak Lab — Thanksgiving, November 2026 (US Eastern), like halloween.js.
   From December 1 this does nothing and the site looks as it always does, so nobody has to
   remember to take it down (the file and its <script> tags can be deleted any time after).
   Loaded in each page's <head>: it adds class "thanksgiving" to <html> and thanksgiving.css
   (a warm harvest background), then once the page is parsed: a thank-you banner under the
   header (one line, with an x that hides it for that browser), autumn leaves drifting down
   behind the content, and a row of pumpkins, pie and corn above the footer. The brand green
   is left alone: on this site green means a hit, an edge or a price that moved our way.
   ?thanksgiving=1 or ?thanksgiving=0 on any page forces it on or off, for checking. */
(function () {
  var END = Date.UTC(2026, 11, 1, 5);        // December 1, 2026, midnight EST
  var q = /[?&]thanksgiving=([01])/.exec(location.search);
  if (q ? q[1] === '0' : Date.now() >= END) return;

  var root = document.documentElement;
  root.classList.add('thanksgiving');
  var css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = '/thanksgiving.css?v=20261101a';
  document.head.appendChild(css);

  var HIDE = 'ps-tg-banner-hidden';
  function hidden() { try { return localStorage.getItem(HIDE) === '1'; } catch (e) { return false; } }

  // leaf colors: amber, rust, deep red, gold
  var COLORS = ['#e8892b', '#c4521c', '#a8321e', '#e6b23a'];
  function leaf(c) {        // a maple leaf
    return '<svg viewBox="0 0 40 40" aria-hidden="true"><path fill="' + c + '" d="M20 2l3.2 7 4.8-2.2-1.2 8.6 6.4-5.2' +
      '.8 3.8 4.8-.6-2.4 6.8 3.6 1.6-7.6 6 1 3.2-8.2-1.4.4 9.4h-3.2l.4-9.4-8.2 1.4 1-3.2-7.6-6 3.6-1.6L1.2 9.4l4.8.6' +
      '.8-3.8 6.4 5.2-1.2-8.6L16.8 9z"/><path d="M20 22v16" stroke="#5a2a10" stroke-width="1.2"/></svg>';
  }
  function oak(c) {         // a rounder oak leaf, for variety
    return '<svg viewBox="0 0 40 40" aria-hidden="true"><path fill="' + c + '" d="M20 3c3 2 2 5 5 5s3 4 1 6c3 0 5 2 3 5' +
      ' 3 1 3 4 0 6 1 3-2 5-5 4-1 2-3 3-4 5-1-2-3-3-4-5-3 1-6-1-5-4-3-2-3-5 0-6-2-3 0-5 3-5-2-2-2-6 1-6s2-3 5-5z"/>' +
      '<path d="M20 8v30" stroke="#5a2a10" stroke-width="1.2"/></svg>';
  }
  var PUMPKIN =
    '<svg viewBox="0 0 64 50" aria-hidden="true">' +
    '<path d="M33 9c0-5 3-7 7-8" fill="none" stroke="#6b8e3a" stroke-width="4" stroke-linecap="round"/>' +
    '<ellipse cx="20" cy="30" rx="13" ry="18" fill="#c9600f"/><ellipse cx="44" cy="30" rx="13" ry="18" fill="#c9600f"/>' +
    '<ellipse cx="32" cy="30" rx="15" ry="20" fill="#e8852b"/></svg>';
  var PIE =
    '<svg viewBox="0 0 64 34" aria-hidden="true">' +
    '<path d="M4 14h56l-5 18H9z" fill="#b8742f"/>' +
    '<ellipse cx="32" cy="14" rx="28" ry="9" fill="#c9601f"/>' +
    '<path d="M4 14c4 4 8 4 12 0 4 4 8 4 12 0 4 4 8 4 12 0 4 4 8 4 12 0 4 4 6 3 8 0" fill="none" stroke="#e9b26a" stroke-width="3" stroke-linecap="round"/>' +
    '<ellipse cx="32" cy="11" rx="7" ry="3" fill="#fff3e0"/></svg>';
  var CORN =
    '<svg viewBox="0 0 30 60" aria-hidden="true">' +
    '<path d="M15 6c7 0 9 10 9 22s-4 22-9 22-9-10-9-22S8 6 15 6z" fill="#e6b23a"/>' +
    '<path d="M10 16h10M9 24h12M9 32h12M10 40h10M15 8v40" stroke="#b8862a" stroke-width="1.4"/>' +
    '<path d="M15 58C8 50 2 40 4 28c4 8 8 14 11 30zM15 58c7-8 13-18 11-30-4 8-8 14-11 30z" fill="#9a7a3a"/></svg>';

  function banner() {
    if (hidden()) return;
    // under the full-width header (boards, home); content pages keep their bar inside a narrow
    // column, so there it goes across the very top of the page instead
    var top = document.querySelector('.apptop, header.top');
    var b = document.createElement('div');
    b.className = 'tg-banner';
    b.setAttribute('role', 'note');
    b.innerHTML = '<span class="tg-leaf" aria-hidden="true">' + leaf('#e8892b') + '</span>' +
      '<p><b>Happy Thanksgiving!</b> We’re thankful for each and every one of you who uses Prop Streak Lab. ' +
      '<span>Thank you for being here.</span></p>' +
      '<button type="button" class="tg-x" aria-label="Hide this message">×</button>';
    b.querySelector('.tg-x').addEventListener('click', function () {
      b.remove();
      try { localStorage.setItem(HIDE, '1'); } catch (e) { /* private window: hidden for this page only */ }
    });
    if (top) top.parentNode.insertBefore(b, top.nextSibling);
    else document.body.insertBefore(b, document.body.firstChild);
  }

  function decorate() {
    banner();

    // leaves drifting down behind the content: left edge, seconds per fall, start offset, size, shape
    var deco = document.createElement('div');
    deco.className = 'tg-deco';
    deco.setAttribute('aria-hidden', 'true');
    var html = '';
    [[4, 17, -2, 1, 0], [13, 23, -14, .7, 1], [27, 20, -7, .8, 0, ' tg-m'], [45, 26, -19, .6, 1, ' tg-m'],
     [62, 19, -4, .75, 0, ' tg-m'], [78, 24, -11, .9, 1], [91, 18, -16, .8, 0], [86, 28, -24, .6, 1, ' tg-m']
    ].forEach(function (v, i) {
      var c = COLORS[i % COLORS.length];
      html += '<span class="tg-fall' + (v[5] || '') + (i % 2 ? ' rev' : '') + '" style="--x:' + v[0] + '%;--d:' + v[1] +
        's;--delay:' + v[2] + 's;--s:' + v[3] + '">' + (v[4] ? oak(c) : leaf(c)) + '</span>';
    });
    deco.innerHTML = html;
    document.body.appendChild(deco);

    // a harvest row at the bottom of the page, above the footer: never under any text
    var row = document.createElement('div');
    row.className = 'tg-harvest';
    row.setAttribute('aria-hidden', 'true');
    row.innerHTML = [[CORN, 26, ' tg-m'], [PUMPKIN, 52], [leaf('#c4521c'), 26], [PIE, 70], [PUMPKIN, 66],
                     [oak('#e6b23a'), 24], [PUMPKIN, 44], [CORN, 26, ' tg-m']].map(function (v) {
      return '<span class="' + (v[2] || '').trim() + '" style="--w:' + v[1] + 'px">' + v[0] + '</span>';
    }).join('');
    var feet = document.querySelectorAll('footer'), foot = feet[feet.length - 1];
    if (foot) foot.parentNode.insertBefore(row, foot);
    else (document.querySelector('main') || document.body).appendChild(row);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', decorate);
  else decorate();
})();
