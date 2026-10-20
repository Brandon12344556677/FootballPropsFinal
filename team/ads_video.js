// 15-second video ads for the Meta ads panel (team/index.html), built on team/ads.js (window.psaAds).
// The owner films one take of the script; this cuts it with the ad's story image, an optional screen recording,
// captions and an end card on a canvas, and records that with MediaRecorder. Clips are opened locally, never uploaded.
(function(){
  'use strict';
  const $ = id => document.getElementById(id);
  const A = window.psaAds;
  if (!A || !$('adVideo')) return;
  const W = 1080, H = 1920, FPS = 30, DUR = 15, TALK = 13;   // the voice runs 0-13s, the end card 13-15s
  const TYPES = ['video/mp4;codecs=avc1.640028,mp4a.40.2', 'video/mp4;codecs=avc1,mp4a.40.2', 'video/mp4',
    'video/webm;codecs=vp9,opus', 'video/webm'];
  const type = window.MediaRecorder ? TYPES.find(t => MediaRecorder.isTypeSupported(t)) || '' : null;
  const cv = $('avCanvas'), g = cv.getContext('2d');
  let cur = null, imgCv = null, endCv = null, face = null, screen = null, ac = null, dest = null, busy = false, out = null, outName = '';

  // ---------- script -> timeline ----------
  const words = s => s.trim().split(/\s+/).filter(Boolean);
  function parts(){   // the textarea: one line each for the opening, the middle and the closing
    const l = $('avScript').value.split('\n').map(s => s.trim()).filter(Boolean);
    return {hook: l[0] || '', middle: l.slice(1, -1).join(' ') || '', cta: l.length > 1 ? l[l.length-1] : ''};
  }
  function chunks(s, a, b){   // caption pieces of up to 4 words, breaking after punctuation, timed by word count
    const w = words(s), out = []; let c = [];
    w.forEach((x, i) => { c.push(x); if (c.length === 4 || /[.,?!:;]$/.test(x) || i === w.length-1){ out.push(c); c = []; } });
    let t = a; const per = (b - a) / (w.length || 1);
    return out.map(c => ({a: t, b: (t += c.length*per), s: c.join(' ')}));
  }
  function timeline(){
    const p = parts(), nh = words(p.hook).length, nm = words(p.middle).length, nc = words(p.cta).length, n = nh + nm + nc || 1;
    const hookEnd = Math.min(4, Math.max(1.5, TALK*nh/n)), ctaStart = Math.max(9.5, Math.min(11.5, TALK - TALK*nc/n));
    const split = screen ? (hookEnd + ctaStart) / 2 : ctaStart;
    return {
      segs: [{a:0, b:hookEnd, pic:'face'}, {a:hookEnd, b:split, pic:'image'}, {a:split, b:ctaStart, pic:'screen'},
        {a:ctaStart, b:TALK, pic:'face'}, {a:TALK, b:DUR, pic:'end'}].filter(s => s.b > s.a),
      caps: [...chunks(p.hook, 0, hookEnd), ...chunks(p.middle, hookEnd, ctaStart), ...chunks(p.cta, ctaStart, TALK)],
      img: [hookEnd, split]
    };
  }

  // ---------- drawing ----------
  function cover(v){
    g.fillStyle = '#0a1628'; g.fillRect(0, 0, W, H);
    if (!v || !v.videoWidth) return;
    const s = Math.max(W/v.videoWidth, H/v.videoHeight), w = v.videoWidth*s, h = v.videoHeight*s;
    g.drawImage(v, (W-w)/2, (H-h)/2, w, h);
  }
  function zoom(c, p){   // slow push-in, 100% -> 106%
    const s = 1 + 0.06*Math.max(0, Math.min(1, p)), w = W*s, h = H*s;
    g.drawImage(c, (W-w)/2, (H-h)/2, w, h);
  }
  function caption(s){
    g.font = '800 62px Inter, sans-serif'; g.textAlign = 'center';
    const lines = []; let line = '';
    for (const w of s.split(' ')){ const t = line ? line + ' ' + w : w; if (g.measureText(t).width > W - 160 && line){ lines.push(line); line = w; } else line = t; }
    if (line) lines.push(line);
    const lh = 78, bh = lines.length*lh + 44, bw = Math.max(...lines.map(l => g.measureText(l).width)) + 72, by = H - 220 - 120 - bh;
    g.fillStyle = 'rgba(6,14,26,.78)'; g.beginPath(); g.roundRect((W-bw)/2, by, bw, bh, 28); g.fill();
    g.fillStyle = '#ffffff'; lines.forEach((l, i) => g.fillText(l, W/2, by + 22 + 58 + i*lh));
    g.textAlign = 'left';
  }
  function frame(tl, t){
    const seg = tl.segs.find(s => t >= s.a && t < s.b) || tl.segs[tl.segs.length-1];
    if (seg.pic === 'end') g.drawImage(endCv, 0, 0);
    else if (seg.pic === 'face') cover(face);
    else if (seg.pic === 'screen') cover(screen);
    else zoom(imgCv, (t - tl.img[0]) / (tl.img[1] - tl.img[0]));
    const c = tl.caps.find(c => t >= c.a && t < c.b);
    if (c && seg.pic !== 'end') caption(c.s);
    return seg;
  }

  // ---------- clips ----------
  function clip(file){
    const v = document.createElement('video');
    v.playsInline = true; v.preload = 'auto'; v.src = URL.createObjectURL(file);
    $('avClips').appendChild(v);   // kept in the page (invisibly) so every browser decodes it
    return new Promise((res, rej) => { v.onloadeddata = () => res(v); v.onerror = () => rej(new Error('bad clip')); });
  }
  const seek = (v, t) => new Promise(res => { if (Math.abs(v.currentTime - t) < 0.01){ res(); return; } v.onseeked = () => { v.onseeked = null; res(); }; v.currentTime = t; });
  async function pick(input, which){
    const f = input.files && input.files[0], msg = which === 'face' ? $('avFaceMsg') : $('avScreenMsg');
    const old = which === 'face' ? face : screen; if (old){ old.pause(); old.remove(); }
    if (which === 'face') face = null; else screen = null;
    msg.textContent = '';
    if (f){
      try {
        const v = await clip(f); if (which === 'face') face = v; else { v.muted = true; screen = v; }
        msg.textContent = `Loaded · ${v.duration.toFixed(1)} s`;
        if (which === 'face' && v.duration < TALK) msg.textContent += ` · shorter than ${TALK} s, so the last frame holds`;
      } catch(e){ msg.textContent = 'This browser can\'t play that file. Try Safari, or export it as MP4.'; }
    }
    $('avMake').disabled = !face || busy || type === null; poster();
  }
  function audio(){   // the owner's voice goes into the recording and out of the speakers
    if (!ac){ ac = new (window.AudioContext || window.webkitAudioContext)(); dest = ac.createMediaStreamDestination(); }
    if (!face._src){ face._src = ac.createMediaElementSource(face); face._src.connect(dest); face._src.connect(ac.destination); }
  }

  // ---------- make ----------
  function poster(){ if (cur && !busy) frame(timeline(), (timeline().img[0] + timeline().img[1]) / 2); }
  async function make(){
    if (busy || !face || !cur) return;
    busy = true; $('avMake').disabled = true; $('avSave').hidden = true; $('avOut').hidden = true; cv.hidden = false;
    const msg = $('avMsg'), tl = timeline(), start = Math.max(0, parseFloat($('avStart').value) || 0);
    try {
      await A.fonts(); audio(); await ac.resume();
      face.pause(); await seek(face, Math.min(start, Math.max(0, face.duration - 0.1)));
      if (screen){ screen.pause(); await seek(screen, 0); }
      const stream = cv.captureStream(FPS); stream.addTrack(dest.stream.getAudioTracks()[0]);
      const rec = new MediaRecorder(stream, type ? {mimeType: type, videoBitsPerSecond: 8e6} : {}), parts = [];
      rec.ondataavailable = e => { if (e.data.size) parts.push(e.data); };
      const stopped = new Promise(res => rec.onstop = res);
      frame(tl, 0); rec.start(250); await face.play();
      const t0 = performance.now(); let screenOn = false, left = false;
      const onVis = () => { if (document.hidden) left = true; };   // a hidden tab stops drawing frames, so the video would freeze
      document.addEventListener('visibilitychange', onVis);
      await new Promise(res => {
        const tick = () => {
          const t = (performance.now() - t0) / 1000;
          if (t >= DUR || left){ res(); return; }
          const seg = frame(tl, t);
          if (seg.pic === 'screen' && screen && !screenOn){ screenOn = true; screen.play(); }
          msg.textContent = `Recording… ${Math.ceil(DUR - t)} s left. Keep this tab in front.`;
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      });
      rec.stop(); face.pause(); if (screen) screen.pause();
      await stopped; stream.getVideoTracks().forEach(t => t.stop()); document.removeEventListener('visibilitychange', onVis);
      if (left){ msg.textContent = 'Stopped: the tab was hidden while recording. Keep this tab in front and make it again.'; busy = false; $('avMake').disabled = false; return; }
      const mt = (rec.mimeType || type || 'video/webm').split(';')[0], ext = mt.includes('mp4') ? 'mp4' : 'webm';
      out = new Blob(parts, {type: mt});
      const day = new Date().toLocaleDateString('en-CA', {timeZone:'America/New_York'});
      outName = `prop-streak-lab-meta-${cur.k}-video-${day}.${ext}`;
      $('avOut').src = URL.createObjectURL(out); $('avOut').hidden = false; cv.hidden = true; $('avSave').hidden = false;
      msg.textContent = ext === 'mp4' ? 'Done. Watch it here, then download.'
        : 'Done, but this browser saves WebM. For an MP4 that Meta takes everywhere, make it in Safari or a current Chrome.';
    } catch(e){
      msg.textContent = 'Recording failed: ' + (e && e.message || e) + '. Try Safari or a current Chrome.';
    }
    busy = false; $('avMake').disabled = !face || type === null;
  }
  function save(){
    if (!out) return;
    const a = document.createElement('a'); a.href = URL.createObjectURL(out); a.download = outName; document.body.appendChild(a); a.click(); a.remove();
    $('avMsg').textContent = 'Downloaded. On an iPhone, if it opened in a new tab, use the share button to save it.';
  }

  // ---------- called by ads.js when the Video size is picked, or the ad / prop changes ----------
  A.onVideo = ({k, ad, arg}) => {
    if (busy) return;
    cur = {k, ad, arg};
    const s = ad.script(arg); $('avScript').value = [s.hook, s.middle, s.cta].join('\n');
    imgCv = document.createElement('canvas'); imgCv.width = W; imgCv.height = H; A.paint(imgCv.getContext('2d'), W, H, k, arg, true);
    endCv = document.createElement('canvas'); endCv.width = W; endCv.height = H; A.endCard(endCv.getContext('2d'), W, H, k, arg);
    $('avOut').hidden = true; $('avSave').hidden = true; cv.hidden = false;
    if (type === null) $('avMsg').textContent = 'This browser can\'t record video. Use Safari or a current Chrome.';
    $('avMake').disabled = !face || type === null;
    poster();
  };
  $('avFace').addEventListener('change', e => pick(e.target, 'face'));
  $('avScreen').addEventListener('change', e => pick(e.target, 'screen'));
  $('avScript').addEventListener('input', poster);
  $('avMake').addEventListener('click', make);
  $('avSave').addEventListener('click', save);
  $('avCopyScript').addEventListener('click', async e => {
    try { await navigator.clipboard.writeText($('avScript').value); e.target.textContent = 'Copied'; } catch(err){ $('avScript').select(); e.target.textContent = 'Press Ctrl+C'; }
    setTimeout(() => e.target.textContent = 'Copy script', 2000);
  });
})();
