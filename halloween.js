/* Prop Streak Lab — Halloween, through October 31, 2026 (US Eastern).
   From November 1 this does nothing and the site looks as it always does, so nobody has to
   remember to take it down (the file and its <script> tags can be deleted any time after).
   Loaded in each page's <head>: it adds class "halloween" to <html> and halloween.css (the
   colors), then the decorations once the page is parsed: a pumpkin logo, a banner with a
   countdown, a "Halloween Edition" badge over the headline, a moon, cobwebs, dangling spiders,
   jack-o'-lanterns and fog along the bottom, bats and ghosts drifting behind the content, and a
   ghost that peeks up from the corner now and then. On the home page every green turns
   orange (its own styles hard-code it in ~50 places, and the ticker and demo card draw more
   after load). ?halloween=1 or ?halloween=0 on any page forces it on or off, for checking. */
(function () {
  var END = Date.UTC(2026, 10, 1, 4);        // November 1, 2026, midnight EDT
  var q = /[?&]halloween=([01])/.exec(location.search);
  if (q ? q[1] === '0' : Date.now() >= END) return;

  var root = document.documentElement;
  var home = /^\/(index\.html)?$/.test(location.pathname);
  root.classList.add('halloween');
  if (home) {
    root.classList.add('hw-home');
    root.style.setProperty('--hw-hit', '#ff7a18');   // no green left on the home page, hits included
  }
  var css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = '/halloween.css?v=20261008d';
  document.head.appendChild(css);

  // ---- every green -> pumpkin orange (home page): style sheets, then attributes, then anything drawn later
  var GREEN = /rgba?\(\s*34,\s*208,\s*127/g, HEX = /#22d07f/gi,
      MINT = /#86e6b6|rgb\(\s*134,\s*230,\s*182\s*\)/gi, INK = /#06210b|rgb\(\s*6,\s*33,\s*11\s*\)/gi;
  function swap(v) {
    return v.replace(GREEN, function (m) { return m.replace(/34,\s*208,\s*127/, '255, 122, 24'); })
            .replace(HEX, '#ff7a18').replace(MINT, '#ffb37a').replace(INK, '#2b1200');
  }
  function recolorRules(rules) {
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i];
      if (r.style) {
        for (var j = 0; j < r.style.length; j++) {
          var p = r.style[j], v = r.style.getPropertyValue(p), n = swap(v);
          if (n !== v) r.style.setProperty(p, n, r.style.getPropertyPriority(p));
        }
      }
      if (r.cssRules) recolorRules(r.cssRules);
    }
  }
  function recolorSheets() {
    for (var i = 0; i < document.styleSheets.length; i++) {
      try { recolorRules(document.styleSheets[i].cssRules); } catch (e) { /* another site's sheet */ }
    }
  }
  var ATTRS = ['style', 'fill', 'stroke', 'stop-color'];
  function recolorNode(el) {
    if (!el.getAttribute) return;
    ATTRS.forEach(function (a) {
      var v = el.getAttribute(a);
      if (v) { var n = swap(v); if (n !== v) el.setAttribute(a, n); }
    });
  }
  function recolorTree(el) {
    if (el.nodeType !== 1) return;
    recolorNode(el);
    el.querySelectorAll('[style],[fill],[stroke],[stop-color]').forEach(recolorNode);
  }

  var PUMPKIN =
    '<rect width="64" height="64" rx="14" fill="#1b0f30"/>' +
    '<path d="M33 17c0-5 3-8 8-9" fill="none" stroke="#6cc04a" stroke-width="4" stroke-linecap="round"/>' +
    '<ellipse cx="21" cy="38" rx="12" ry="16" fill="#d9590b"/><ellipse cx="43" cy="38" rx="12" ry="16" fill="#d9590b"/>' +
    '<ellipse cx="32" cy="38" rx="13" ry="18" fill="#ff7a18"/>' +
    '<path d="M20 33l5-6 5 6zM34 33l5-6 5 6z" fill="#2b1200"/>' +
    '<path d="M19 41c4 7 22 7 26 0l-4 1-2 3-3-3-3 3-3-3-3 3-2-3z" fill="#2b1200"/>';
  var JACK =      // a lit jack-o'-lantern, no tile behind it
    '<svg viewBox="0 0 64 54" aria-hidden="true">' +
    '<path d="M33 9c0-5 3-7 7-8" fill="none" stroke="#5aa83c" stroke-width="4" stroke-linecap="round"/>' +
    '<ellipse cx="20" cy="31" rx="13" ry="20" fill="#c9500a"/><ellipse cx="44" cy="31" rx="13" ry="20" fill="#c9500a"/>' +
    '<ellipse cx="32" cy="31" rx="15" ry="22" fill="#ff7a18"/>' +
    '<path class="hw-face" d="M19 25l6-7 6 7zM33 25l6-7 6 7zM17 35c5 9 25 9 30 0l-5 1-2 4-4-4-4 4-4-4-4 4-2-4z" fill="#ffd23f"/></svg>';
  var BAT =
    '<svg viewBox="0 0 64 30" aria-hidden="true"><path fill="#1a0f2e" d="M32 9c1.5-3 3.5-4.5 5.5-4.5-.6 2 .1 3.6 1.6 4.4' +
    'C43 5 50 3.5 58 5.5c-4 2-6 5.5-6 9.5-3-2.3-7-2.4-10 .2-1.8-2.8-4.6-3.7-7.4-2.6-.9 1.6-1.8 2.8-2.6 4.4' +
    '-.8-1.6-1.7-2.8-2.6-4.4-2.8-1.1-5.6-.2-7.4 2.6-3-2.6-7-2.5-10-.2 0-4-2-7.5-6-9.5 8-2 15-.5 18.9 3.4' +
    ' 1.5-.8 2.2-2.4 1.6-4.4 2 0 4 1.5 5.5 4.5z"/></svg>';
  var GHOST =
    '<svg viewBox="0 0 40 48" aria-hidden="true"><path fill="#f1ecff" fill-opacity=".85" d="M20 2C9.5 2 4 10 4 20v25' +
    'l5.3-4.2 5.4 4.2 5.3-4.2 5.3 4.2 5.4-4.2L36 45V20C36 10 30.5 2 20 2z"/>' +
    '<ellipse cx="14.5" cy="19" rx="3" ry="4" fill="#1b0f30"/><ellipse cx="25.5" cy="19" rx="3" ry="4" fill="#1b0f30"/>' +
    '<ellipse cx="20" cy="29" rx="3" ry="2.4" fill="#1b0f30"/></svg>';
  var SPIDER =
    '<svg viewBox="0 0 40 36" aria-hidden="true"><g fill="none" stroke="#2a1840" stroke-width="2.2" stroke-linecap="round">' +
    '<path d="M16 16 6 8 2 14M16 19 4 18 1 24M16 22 6 26 4 33M24 16l10-8 4 6M24 19l12-1 3 6M24 22l10 4 2 7"/></g>' +
    '<ellipse cx="20" cy="21" rx="7" ry="8" fill="#1a0f2e"/><circle cx="20" cy="11" r="4.5" fill="#1a0f2e"/>' +
    '<circle cx="18.3" cy="10.5" r="1.1" fill="#ff4d2e"/><circle cx="21.7" cy="10.5" r="1.1" fill="#ff4d2e"/></svg>';

  function web() {          // a corner cobweb: spokes from the corner, sagging threads between them
    var angs = [0, 14, 30, 46, 62, 76, 90].map(function (a) { return a * Math.PI / 180; });
    var d = '', f = function (n) { return n.toFixed(1); };
    angs.forEach(function (a) { d += 'M0 0L' + f(160 * Math.cos(a)) + ' ' + f(160 * Math.sin(a)); });
    [22, 46, 74, 106, 140].forEach(function (r) {
      for (var i = 0; i < angs.length - 1; i++) {
        var a1 = angs[i], a2 = angs[i + 1], am = (a1 + a2) / 2, s = r * 0.88;
        if (!i) d += 'M' + f(r * Math.cos(a1)) + ' ' + f(r * Math.sin(a1));
        d += 'Q' + f(s * Math.cos(am)) + ' ' + f(s * Math.sin(am)) + ' ' + f(r * Math.cos(a2)) + ' ' + f(r * Math.sin(a2));
      }
    });
    return '<svg viewBox="0 0 160 160" aria-hidden="true"><path d="' + d + '" fill="none" stroke="#e6dcff" stroke-width="1"/></svg>';
  }

  function daysLeft() {     // days from today (US Eastern) to October 31
    var p = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: 'numeric', day: 'numeric' })
      .formatToParts(new Date()).reduce(function (o, x) { o[x.type] = +x.value; return o; }, {});
    return Math.round((Date.UTC(2026, 9, 31) - Date.UTC(p.year, p.month - 1, p.day)) / 864e5);
  }

  function decorate() {
    if (home) {
      recolorSheets();
      recolorTree(document.body);
      new MutationObserver(function (ms) {
        ms.forEach(function (m) {
          if (m.type === 'attributes') recolorNode(m.target);
          else m.addedNodes.forEach(recolorTree);
        });
      }).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ATTRS });
    }
    // the logo (the four-point star) becomes a jack-o'-lantern, wherever it appears
    document.querySelectorAll('svg path[d^="M32,6 Q32,32"]').forEach(function (p) {
      var svg = p.closest('svg');
      if (svg) svg.innerHTML = PUMPKIN;
    });

    var n = daysLeft();
    var b = document.createElement('div');
    b.className = 'hw-banner';
    b.setAttribute('role', 'note');
    b.innerHTML = '🎃 <b>Happy Halloween</b> from Prop Streak Lab 👻' +
      '<em class="hw-count">' + (n > 0 ? '🍬 ' + n + ' day' + (n === 1 ? '' : 's') + ' to Halloween' : '🎃 It\'s Halloween!') + '</em>' +
      '<span>No tricks, just the picks.</span>';
    var h = document.querySelector('header');
    if (h) h.insertAdjacentElement('afterend', b); else document.body.insertBefore(b, document.body.firstChild);

    var h1 = document.querySelector('main h1, .apphero h1, h1');
    if (h1) {
      var badge = document.createElement('div');
      badge.className = 'hw-badge';
      badge.innerHTML = '🎃 Halloween Edition <small>through Oct 31</small>';
      h1.insertAdjacentElement('beforebegin', badge);
    }

    var deco = document.createElement('div');
    deco.className = 'hw-deco';
    deco.setAttribute('aria-hidden', 'true');
    var html = '<div class="hw-moon"></div><div class="hw-fog"></div>' +
      '<div class="hw-web hw-web-l">' + web() + '</div><div class="hw-web hw-web-r">' + web() + '</div>';
    // spiders: left edge, thread length, seconds per bob; the last skips phones
    [[5, 120, 6], [94, 190, 8], [70, 80, 7, ' hw-m']].forEach(function (v) {
      html += '<span class="hw-spider' + (v[3] || '') + '" style="--x:' + v[0] + '%;--len:' + v[1] + 'px;--d:' + v[2] + 's">' +
        '<i></i>' + SPIDER + '</span>';
    });
    // a jack-o'-lantern in each bottom corner (wide screens only, where the margins are empty)
    html += '<span class="hw-jack l" style="--delay:0s">' + JACK + '</span><span class="hw-jack r" style="--delay:-.9s">' + JACK + '</span>';
    // bats: height on screen, seconds per crossing, start offset, size, direction; the last two skip phones
    [[14, 26, -4, 1, ''], [32, 34, -20, .7, ' rev'], [58, 29, -11, .85, ''], [22, 41, -30, .6, ' rev hw-m'],
     [72, 37, -7, .75, ' rev hw-m']].forEach(function (v, i) {
      html += '<span class="hw-bat' + v[4] + '" style="--y:' + v[0] + '%;--d:' + v[1] + 's;--delay:' + v[2] +
        's;--s:' + v[3] + ';--x:' + (12 + i * 19) + 'vw">' + BAT + '</span>';
    });
    // ghosts: left, top, seconds per drift, size; the last one skips phones
    [[3, 38, 9, 1], [90, 62, 11, .8], [47, 84, 13, .7, ' hw-m']].forEach(function (v) {
      html += '<span class="hw-ghost' + (v[4] || '') + '" style="--x:' + v[0] + '%;--y:' + v[1] + '%;--d:' + v[2] +
        's;--s:' + v[3] + '">' + GHOST + '</span>';
    });
    deco.innerHTML = html;
    document.body.appendChild(deco);

    // a pumpkin patch at the bottom of the page, above the footer: never under any text
    var patch = document.createElement('div');
    patch.className = 'hw-patch';
    patch.setAttribute('aria-hidden', 'true');
    patch.innerHTML = [46, 64, 38, 78, 52, 40, 60].map(function (w, i) {
      return '<span style="--w:' + w + 'px;--delay:' + (-i * .7) + 's"' + (i === 0 || i === 6 ? ' class="hw-m"' : '') + '>' + JACK + '</span>';
    }).join('');
    var feet = document.querySelectorAll('footer'), foot = feet[feet.length - 1];
    if (foot) foot.parentNode.insertBefore(patch, foot);
    else (document.querySelector('main') || document.body).appendChild(patch);

    var peek = document.createElement('div');      // the ghost that peeks up from the corner: in front, but never in the way
    peek.className = 'hw-peek';
    peek.setAttribute('aria-hidden', 'true');
    peek.innerHTML = '<b>Boo!</b>' + GHOST;
    document.body.appendChild(peek);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', decorate);
  else decorate();
})();
