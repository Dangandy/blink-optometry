/* ==========================================================================
   Blink Optometry — intro choreography + frame5 → live-hero handoff
   --------------------------------------------------------------------------
   One rAF-throttled scroll/resize driver computes two scalars:
     p — intro progress, 0..1 over INTRO_TRAVEL_VH viewport heights
     q — post-intro release, 0..1 over RELEASE_VH viewport heights after p=1
   Every visual (layer opacities, letterbox colour, rim transform, hero-lockup
   transform) is a pure function of (p, q), so scrubbing backwards is exact.
   ========================================================================== */
(function () {
  'use strict';

  /* ── Tunable constants (QA calibrates these) ───────────────────────────── */

  // Lockup box width as a fraction of the on-screen lens DIAMETER at handoff.
  // The box is frame5's total lockup ink block: 614.2 image px wide over a
  // 756.4 px lens diameter. Its height follows from CSS aspect-ratio (92.152 %).
  var LOCKUP_TO_LENS = 0.812;
  // Lockup centre offset from the lens centre, in lens DIAMETERS.
  // frame5's ink block is centred at image (524.5, 740) vs lens (533, 717.5).
  var LOCKUP_X_OFFSET = -0.0112;   // + = right
  var LOCKUP_Y_OFFSET = 0.0300;    // + = down
  // Rim scale at the end of the release (becomes a soft corner frame).
  // This is the CAP: measureViewport() clamps it per-viewport so the ring's
  // hole edge never recedes past the farthest viewport corner (see rimFinalScale).
  var RIM_FINAL_SCALE = 2.5;
  // f3 → f4 push-in: the zoom dives into frame3's RIGHT lens. Expressed in
  // frame3 IMAGE pixels (1024×1536) and converted to a box-relative origin per
  // viewport, so the dive stays on the lens under object-fit: cover cropping.
  // Chosen so frame3's right lens (image cx 800, cy 736) is carried onto
  // frame4's lens centre (533, 717.5) as the scale reaches ~1.55 — the two lens
  // rings end up concentric mid-crossfade instead of reading as a double
  // exposure. Off-image x is intentional: the fixed point sits to the right, so
  // the frame both grows and swings the right lens into the middle.
  var F3_ORIGIN_IMG = { x: 1312, y: 771 };
  var F3_PUSH_SCALE = 0.55;   // f3 scales 1 → 1 + this over T.f4In
  var F4_PUSH_SCALE = 0.06;   // f4 scales 1 - this → exactly 1.00 over T.f4In
  // Sticky travel of the intro stage, in viewport heights (#intro is this + 1).
  var INTRO_TRAVEL_VH = 3;
  // Length of the post-intro release, in viewport heights.
  var RELEASE_VH = 1.5;
  // Stage scale before "the click" snaps it back to 1.
  var STAGE_SCALE_START = 1.02;

  // Timeline — matches the plan's choreography table. All values are p.
  var T = {
    f2In:      [0.10, 0.30],  // crossfade frame1 → frame2
    cut:        0.38,         // HARD CUT to frame3
    f4In:      [0.45, 0.62],  // crossfade frame3 → frame4
    click:     [0.68, 0.74],  // THE CLICK: frame4 → frame5 + scale snap
    rimIn:     [0.78, 0.92],  // rim overlay fades in, then persists
    lbColor:   [0.78, 0.90],  // letterbox black → page white
    stillsOut: [0.80, 1.00],  // stills dissolve, live hero underneath
    lbOut:     [0.84, 1.00]   // letterbox dissolves, live hero visible
  };

  /* ── Baked measurements (from tools/make_rim.py — do NOT fetch at runtime) */
  var M = {
    image:       { w: 1024, h: 1536 },
    rim_hole:    { cx: 522.0, cy: 692.5, r: 362.8 },
    frame5_lens: { cx: 533.0, cy: 717.5, r: 378.2 },
    teal_hex:    '#03707b'
  };

  /* ── Math helpers ──────────────────────────────────────────────────────── */
  function clamp01(v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }
  function lin01(x, range) {
    var a = range[0], b = range[1];
    return b === a ? (x >= b ? 1 : 0) : clamp01((x - a) / (b - a));
  }
  function smooth01(x, range) { var t = lin01(x, range); return t * t * (3 - 2 * t); }
  function easeOutCubic(t) { var u = 1 - t; return 1 - u * u * u; }
  function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  /* ── DOM ───────────────────────────────────────────────────────────────── */
  var root      = document.documentElement;
  var introEl   = document.getElementById('intro');
  var stageCol  = document.querySelector('.stage-col');
  var frames    = document.querySelector('.stage-frames');
  var letterbox = document.querySelector('.letterbox');
  var scrollCue = document.querySelector('.scroll-cue');
  var f2        = document.getElementById('f2');
  var f3        = document.getElementById('f3');
  var f4        = document.getElementById('f4');
  var f5        = document.getElementById('f5');
  var rim       = document.getElementById('rim');
  var skipBtn   = document.getElementById('skip');
  var stickyCta = document.getElementById('cta-sticky');
  var heroCta   = document.getElementById('hero-cta');
  var lockup    = document.getElementById('hero-lockup');

  /* ── Entry path ────────────────────────────────────────────────────────── */
  // 'normal' — intro plays and drives p from scroll
  // 'off'    — sessionStorage flag or prefers-reduced-motion: p=1, q=1, static
  // 'align'  — ?align=1 calibration: p=1, q=0, static, frame5 overlaid at 50%
  var alignMode = location.search.indexOf('align=1') > -1;
  var mode = alignMode ? 'align' : (root.className.indexOf('no-intro') > -1 ? 'off' : 'normal');

  /* ── Geometry state ────────────────────────────────────────────────────── */
  var vw = 0, vh = 0;              // clientWidth, 100svh in px
  var colW = 0, colX = 0;          // the intro stage's portrait column box
  var lensX = 0, lensY = 0, lensR = 0;
  var rimK = 1, rimTx = 0, rimTy = 0;
  var rimFinalScale = RIM_FINAL_SCALE;   // per-viewport clamp of the cap
  var introTravel = 0;
  var LK = null;                   // untransformed lockup box, in document coords
  var svhProbe = null;
  var alignOverlay = null;
  var heroCtaOnScreen = false;
  var introSeen = false;

  /* ── svh probe: guarantees the JS height matches the CSS 100svh ────────── */
  function makeProbe() {
    svhProbe = document.createElement('div');
    svhProbe.setAttribute('aria-hidden', 'true');
    svhProbe.style.cssText =
      'position:fixed;top:0;left:0;width:0;height:100vh;height:100svh;' +
      'visibility:hidden;pointer-events:none;';
    document.body.appendChild(svhProbe);
  }

  /* ── Viewport / cover math ─────────────────────────────────────────────── */
  function measureViewport() {
    vw = root.clientWidth || window.innerWidth || 0;
    vh = svhProbe ? svhProbe.getBoundingClientRect().height : 0;
    if (!vh) vh = window.innerHeight || 0;

    // The stage column: width min(100%, 100svh * 2/3), height 100svh, centred.
    colW = Math.min(vw, vh * 2 / 3);
    colX = (vw - colW) / 2;

    // object-fit: cover of a 1024×1536 still inside that column.
    var s  = Math.max(colW / M.image.w, vh / M.image.h);
    var ox = colX + (colW - M.image.w * s) / 2;
    var oy = (vh - M.image.h * s) / 2;

    lensX = ox + M.frame5_lens.cx * s;
    lensY = oy + M.frame5_lens.cy * s;
    lensR = M.frame5_lens.r * s;

    // Rim: the rim hole and frame5's lens are NOT concentric — scale by the
    // hole radius, then translate so the HOLE centre lands on the lens centre.
    rimK  = lensR / M.rim_hole.r;
    rimTx = lensX - rimK * M.rim_hole.cx;
    rimTy = lensY - rimK * M.rim_hole.cy;

    // Rim recession clamp: at scale g the hole radius on screen is lensR * g,
    // so keeping lensR * g just inside the farthest viewport corner keeps the
    // ring visible as a soft corner frame on tall/narrow phones.
    var cornerDist = Math.max(
      Math.hypot(lensX,      lensY),
      Math.hypot(vw - lensX, lensY),
      Math.hypot(lensX,      vh - lensY),
      Math.hypot(vw - lensX, vh - lensY)
    );
    rimFinalScale = lensR > 0
      ? Math.min(RIM_FINAL_SCALE, 0.95 * cornerDist / lensR)
      : RIM_FINAL_SCALE;

    // Push-in origin for #f3, in the frame box's own pixels. The frame box is
    // colW × vh and the still is object-fit: cover / 50% 50% inside it, so the
    // image origin maps through the same cover transform used above.
    if (f3) {
      f3.style.transformOrigin =
        ((colW - M.image.w * s) / 2 + F3_ORIGIN_IMG.x * s) + 'px ' +
        ((vh   - M.image.h * s) / 2 + F3_ORIGIN_IMG.y * s) + 'px';
    }
    if (f4) f4.style.transformOrigin = '50% 50%';

    introTravel = INTRO_TRAVEL_VH * vh;

    root.style.setProperty('--lens-x', lensX + 'px');
    root.style.setProperty('--lens-y', lensY + 'px');
    root.style.setProperty('--lens-r', lensR + 'px');
  }

  /* ── Lockup natural box (measured with its own transform cleared) ──────── */
  function measureLockup() {
    if (!lockup) return;
    var prev = lockup.style.transform;
    lockup.style.transform = 'none';
    var r = lockup.getBoundingClientRect();
    LK = {
      w: r.width,
      h: r.height,
      docX: r.left + (window.pageXOffset || 0),
      docY: r.top + (window.pageYOffset || 0)
    };
    lockup.style.transform = prev;
  }

  /* ── Writers ───────────────────────────────────────────────────────────── */
  function applyIntro(p) {
    if (!frames) return;

    if (f2) f2.style.opacity = smooth01(p, T.f2In);

    // f3 → f4 is a directional push-in: the camera dives into frame3's right
    // lens while frame4 (that same lens, filling the frame) rises to meet it.
    // e is 0 below T.f4In and exactly 1 at/above it, so both ends are static
    // and scrubbing back through the range is exact.
    var e = easeInOutCubic(lin01(p, T.f4In));

    if (f3) {
      // Hard cut in at T.cut, then fade out over the SECOND HALF of T.f4In so
      // the dive is well underway before frame3 gives way.
      var f3Mid = (T.f4In[0] + T.f4In[1]) / 2;
      f3.style.opacity = (p < T.cut) ? 0 : (1 - smooth01(p, [f3Mid, T.f4In[1]]));
      f3.style.transform = 'scale(' + (1 + F3_PUSH_SCALE * e) + ')';
    }
    if (f4) {
      // 1 - k*(1 - e) is EXACTLY 1 when e === 1 — frame5's click alignment
      // depends on f4 sitting at unit scale from p = T.f4In[1] onwards.
      f4.style.opacity = smooth01(p, T.f4In);
      f4.style.transform = (e >= 1) ? 'none'
                                    : 'scale(' + (1 - F4_PUSH_SCALE * (1 - e)) + ')';
    }
    if (f5) f5.style.opacity = easeOutCubic(lin01(p, T.click));

    var stillsAlpha = 1 - smooth01(p, T.stillsOut);
    var stageScale  = STAGE_SCALE_START +
                      (1 - STAGE_SCALE_START) * easeOutCubic(lin01(p, T.click));
    frames.style.opacity = stillsAlpha;
    frames.style.transform = 'scale(' + stageScale + ')';

    if (letterbox) {
      // white behind frames 1–2 → black from the cut → back to page white.
      var g;
      if (p < T.cut) g = 255;
      else g = Math.round(255 * smooth01(p, T.lbColor));
      letterbox.style.backgroundColor = 'rgb(' + g + ',' + g + ',' + g + ')';
      letterbox.style.opacity = 1 - lin01(p, T.lbOut);
    }
  }

  function applyRim(p, q) {
    if (!rim) return;
    var g = 1 + (rimFinalScale - 1) * easeInOutCubic(q);
    rim.style.transform =
      'translate(' + lensX + 'px,' + lensY + 'px) scale(' + g + ') ' +
      'translate(' + (-lensX) + 'px,' + (-lensY) + 'px) ' +
      'translate(' + rimTx + 'px,' + rimTy + 'px) scale(' + rimK + ')';
    rim.style.opacity = smooth01(p, T.rimIn);
  }

  function applyLockup(q, scrollY) {
    if (!lockup || !LK || !LK.w) return;
    var t = 1 - easeInOutCubic(q);   // 1 = lens-matched, 0 = identity
    if (t <= 0.0001) { lockup.style.transform = 'none'; return; }

    var natCx = LK.docX + LK.w / 2 - (window.pageXOffset || 0);
    var natCy = LK.docY + LK.h / 2 - scrollY;

    var lensD    = 2 * lensR;
    var targetS  = (LOCKUP_TO_LENS * lensD) / LK.w;
    var targetCx = lensX + LOCKUP_X_OFFSET * lensD;
    var targetCy = lensY + LOCKUP_Y_OFFSET * lensD;

    var dx = (targetCx - natCx) * t;
    var dy = (targetCy - natCy) * t;
    var s  = 1 + (targetS - 1) * t;

    lockup.style.transform =
      'translate(' + dx + 'px,' + dy + 'px) scale(' + s + ')';
  }

  /* Scroll cue: gone by q = 0.25, before the releasing lockup reaches it.
     --cue-fade multiplies the cue's idle bob so the fade survives the
     keyframe animation (animations outrank inline styles in the cascade). */
  function applyCue(q) {
    if (!scrollCue) return;
    scrollCue.style.setProperty('--cue-fade', String(1 - clamp01(q / 0.25)));
  }

  function applyChrome(introActive) {
    if (introEl) introEl.style.pointerEvents = introActive ? 'auto' : 'none';
    if (skipBtn) skipBtn.classList.toggle('is-hidden', !introActive);
    if (stickyCta) {
      // Always visible during the intro; afterwards, yield to the hero's own CTA.
      var hide = !introActive && heroCtaOnScreen;
      stickyCta.classList.toggle('is-hidden', hide);
      if (hide) stickyCta.setAttribute('aria-hidden', 'true');
      else stickyCta.removeAttribute('aria-hidden');
    }
  }

  function applyAlignOverlay() {
    if (!alignOverlay) return;
    alignOverlay.style.left   = colX + 'px';
    alignOverlay.style.top    = '0px';
    alignOverlay.style.width  = colW + 'px';
    alignOverlay.style.height = vh + 'px';
  }

  /* ── The single driver ─────────────────────────────────────────────────── */
  function render() {
    var scrollY = window.pageYOffset || root.scrollTop || 0;
    var p, q, introActive;

    if (mode === 'off') {
      p = 1; q = 1; introActive = false;
    } else if (mode === 'align') {
      p = 1; q = 0; introActive = false; scrollY = 0;  // scroll is pinned
    } else {
      p = introTravel > 0 ? clamp01(scrollY / introTravel) : 1;
      q = clamp01((scrollY - introTravel) / (RELEASE_VH * vh));
      introActive = p < 0.999;
      if (!introActive) markSeen();
      applyIntro(p);
    }

    applyRim(p, q);
    applyLockup(q, scrollY);
    applyCue(q);
    applyChrome(introActive);
  }

  var ticking = false;
  function schedule() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () { ticking = false; render(); });
  }

  function relayout() {
    measureViewport();
    measureLockup();
    applyAlignOverlay();
    render();
  }

  /* ── sessionStorage flag ───────────────────────────────────────────────── */
  function markSeen() {
    if (introSeen) return;
    introSeen = true;
    try { sessionStorage.setItem('blinkIntroSeen', '1'); } catch (e) {}
  }

  /* ── Skip ──────────────────────────────────────────────────────────────── */
  function onSkip() {
    markSeen();
    window.scrollTo({ top: introTravel, left: 0, behavior: 'auto' });
    render();
  }

  /* ── Boot ──────────────────────────────────────────────────────────────── */
  function init() {
    makeProbe();

    if (mode === 'align') {
      alignOverlay = document.createElement('img');
      alignOverlay.id = 'align-overlay';
      alignOverlay.src = 'assets/opt/frame5.webp';
      alignOverlay.width = M.image.w;
      alignOverlay.height = M.image.h;
      alignOverlay.alt = '';
      alignOverlay.setAttribute('aria-hidden', 'true');
      document.body.appendChild(alignOverlay);

      var badge = document.createElement('div');
      badge.id = 'align-badge';
      badge.textContent = 'ALIGN';
      badge.setAttribute('aria-hidden', 'true');
      document.body.appendChild(badge);

      root.style.overflow = 'hidden';
      window.scrollTo(0, 0);
    }

    if (mode === 'off') markSeen();

    relayout();

    if (mode === 'normal') {
      window.addEventListener('scroll', schedule, { passive: true });
    }
    window.addEventListener('resize', relayout);
    window.addEventListener('orientationchange', relayout);
    window.addEventListener('load', relayout);
    if (document.fonts && document.fonts.ready && document.fonts.ready.then) {
      document.fonts.ready.then(function () { measureLockup(); render(); });
    }

    if (skipBtn) skipBtn.addEventListener('click', onSkip);

    if (heroCta && 'IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        heroCtaOnScreen = entries[entries.length - 1].isIntersecting;
        schedule();
      }, { threshold: 0 }).observe(heroCta);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
