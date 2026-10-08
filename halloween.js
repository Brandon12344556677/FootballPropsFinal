/* Prop Streak Lab — Halloween, through October 31, 2026 (US Eastern).
   From November 1 this does nothing and the site looks as it always does, so nobody has to
   remember to take it down (the file and its <script> tags can be deleted any time after).
   Loaded in each page's <head>: it adds class "halloween" to <html> and halloween.css (the
   colors), then the decorations once the page is parsed: a pumpkin logo, a banner under the
   header, cobwebs in the top corners, and bats and ghosts drifting behind the content.
   ?halloween=1 or ?halloween=0 on any page forces it on or off, for checking. */
(function () {
  var END = Date.UTC(2026, 10, 1, 4);        // November 1, 2026, midnight EDT
  var q = /[?&]halloween=([01])/.exec(location.search);
  if (q ? q[1] === '0' : Date.now() >= END) return;

  document.documentElement.classList.add('halloween');
  var css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = '/halloween.css?v=20261008a';
  document.head.appendChild(css);

  var PUMPKIN =
    '<rect width="64" height="64" rx="14" fill="#1b0f30"/>' +
    '<path d="M33 17c0-5 3-8 8-9" fill="none" stroke="#6cc04a" stroke-width="4" stroke-linecap="round"/>' +
    '<ellipse cx="21" cy="38" rx="12" ry="16" fill="#d9590b"/><ellipse cx="43" cy="38" rx="12" ry="16" fill="#d9590b"/>' +
    '<ellipse cx="32" cy="38" rx="13" ry="18" fill="#ff7a18"/>' +
    '<path d="M20 33l5-6 5 6zM34 33l5-6 5 6z" fill="#2b1200"/>' +
    '<path d="M19 41c4 7 22 7 26 0l-4 1-2 3-3-3-3 3-3-3-3 3-2-3z" fill="#2b1200"/>';
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

  function decorate() {
    // the logo (the four-point star) becomes a jack-o'-lantern, wherever it appears
    document.querySelectorAll('svg path[d^="M32,6 Q32,32"]').forEach(function (p) {
      var svg = p.closest('svg');
      if (svg) svg.innerHTML = PUMPKIN;
    });
    var b = document.createElement('div');
    b.className = 'hw-banner';
    b.setAttribute('role', 'note');
    b.innerHTML = '🎃 <b>Happy Halloween</b> from Prop Streak Lab 👻 <span>No tricks, just the picks.</span>';
    var h = document.querySelector('header');
    if (h) h.insertAdjacentElement('afterend', b); else document.body.insertBefore(b, document.body.firstChild);

    var deco = document.createElement('div');
    deco.className = 'hw-deco';
    deco.setAttribute('aria-hidden', 'true');
    var html = '<div class="hw-web hw-web-l">' + web() + '</div><div class="hw-web hw-web-r">' + web() + '</div>';
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
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', decorate);
  else decorate();
})();
