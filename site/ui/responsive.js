/* =====================================================================
   ui/responsive.js  —  Responsive layout module (desktop + mobile)
   Team 268LTK · NASA Space Apps 2026
   AI use: Written with assistance from Claude (Anthropic); reviewed and tested by team 268LTK.

   What this module does (index.html's original code is NOT changed):
     1. Rearranges the controls into 2 rows, the same on desktop and phone:
          row 1: ← Globe · Brand · ⓘ Method ............ ⚙ Settings
          row 2: ⤺ Full view · 🛡 Patrol map · 📊 Calendar & Charts · Heat glow|Grid
     2. Phone (< 900px): the stats/patrol panel becomes a "bottom sheet"
        (collapsed by default, tap the handle to open), the legend becomes
        a small horizontal bar, and the time bar sits just above the sheet.
     3. Fits Vietnam into the area the panels actually leave free
        (measured from the real page), so the panels no longer cover the map.
     4. Phone: pinch with 2 fingers to zoom, tap to see province/cell info.

   Load order: this file MUST come AFTER the main <script> in index.html.
   Remove the module: delete the 2 lines containing "ui/responsive" in index.html.
   ===================================================================== */
(function () {
  'use strict';
  try {
    if (typeof layout !== 'function' || typeof VT === 'undefined') {
      console.warn('[responsive] main script not found, module disabled');
      return;
    }
    const root = document.documentElement;
    const q = s => document.querySelector(s);
    const mq = matchMedia('(max-width: 899px)');   // same breakpoint as the original code (wide = w >= 900)
    const mob = () => mq.matches;
    const PEEK = 100;                               // collapsed sheet height (px)

    const header = q('header'), panel = q('#panel'), map = q('#map');
    if (!header || !panel || !map) return;

    /* ---------- 1. Rearrange the controls ---------- */
    const tools = document.createElement('div');
    tools.id = 'rTools';
    tools.className = 'vnonly';
    ['#fit', '#patrolBtn', '#anaBtn', '#styles'].forEach(s => { const el = q(s); if (el) tools.appendChild(el); });
    const brk = document.createElement('div');
    brk.className = 'rbreak';
    const sw = q('#settingsWrap');
    if (sw) header.appendChild(sw);   // row 1, right after .grow
    header.appendChild(brk);          // line break
    header.appendChild(tools);        // row 2

    /* ---------- 2. Bottom sheet (phone) ---------- */
    const handle = document.createElement('button');
    handle.id = 'rHandle';
    handle.type = 'button';
    handle.setAttribute('aria-label', 'Open / collapse panel');
    handle.innerHTML = '<i></i>';
    panel.insertBefore(handle, panel.firstChild);

    const setOpen = open => {
      panel.classList.toggle('rCollapsed', !open);
      handle.setAttribute('aria-expanded', String(open));
    };
    handle.addEventListener('click', e => { e.stopPropagation(); setOpen(panel.classList.contains('rCollapsed')); });

    // Swipe up/down on the handle
    let sy = null;
    handle.addEventListener('touchstart', e => { sy = e.touches[0].clientY; }, { passive: true });
    handle.addEventListener('touchend', e => {
      if (sy == null) return;
      const dy = e.changedTouches[0].clientY - sy; sy = null;
      if (dy < -25) setOpen(true); else if (dy > 25) setOpen(false);
    });

    // Open the sheet automatically when there is something to read
    q('#topMore')?.addEventListener('click', () => { if (mob()) setOpen(true); });
    const card = q('#patrolCard');
    if (card) new MutationObserver(() => {
      if (mob() && card.classList.contains('show')) { setOpen(true); card.scrollIntoView({ block: 'nearest' }); }
    }).observe(card, { attributes: true, attributeFilter: ['class'] });
    const pBtn = q('#patrolBtn');
    if (pBtn) new MutationObserver(() => {
      if (mob()) setOpen(false);              // switching mode: collapse the sheet so the map stays visible
    }).observe(pBtn, { attributes: true, attributeFilter: ['class'] });

    /* ---------- 3. Legend: keep the gradient direction right ---------- */
    // The original code writes linear-gradient(0deg, ...) inline when the palette changes;
    // the horizontal bar on phones needs 90deg.
    const g = q('#legend .g');
    const fixG = () => {
      if (!g) return;
      const b = g.style.background; if (!b) return;
      const nb = mob() ? b.replace(/gradient\((0deg|to top)/, 'gradient(90deg')
                       : b.replace(/gradient\((90deg|to right)/, 'gradient(0deg');
      if (nb !== b) g.style.background = nb;
    };
    if (g) new MutationObserver(fixG).observe(g, { attributes: true, attributeFilter: ['style'] });

    /* ---------- 4. Fit Vietnam into the free area ---------- */
    const syncMode = () => {
      const was = root.classList.contains('rMob'), now = mob();
      root.classList.toggle('rMob', now);
      if (now && !was) setOpen(false);
      fixG();
    };
    function freeArea() {
      const w = innerWidth, h = innerHeight, m = mob();
      const hd = header.getBoundingClientRect();
      if (m) root.style.setProperty('--rLegTop', Math.round(hd.bottom + 2) + 'px');
      const leg = q('#legend').getBoundingClientRect();
      const bar = q('#bar').getBoundingClientRect();
      const pn = panel.getBoundingClientRect();
      if (m) return { x0: 10, x1: w - 10, top: Math.max(hd.bottom, leg.bottom) + 10, bot: h - Math.min(bar.top, h - PEEK) + 10 };
      return { x0: leg.right + 20, x1: pn.left - 20, top: hd.bottom + 10, bot: h - bar.top + 16 };
    }
    const origLayout = layout;
    layout = function () {           // overrides the global function in index.html
      syncMode();
      origLayout();
      try {
        const { x0, x1, top, bot } = freeArea(), h = innerHeight;
        const W = Math.max(120, x1 - x0), H = Math.max(160, h - top - bot), cx = (x0 + x1) / 2;
        VT = { k: Math.min(H / 2 / .1374, W / 2 / .1105), c: [cx, top + H / 2], rot: [-VNT[0], -VNT[1]] };
        R = { x0: cx - W / 2, x1: cx + W / 2, y0: top, y1: top + H };
      } catch (e) { console.warn('[responsive] fit failed, keeping the original layout', e); }
    };

    root.style.setProperty('--rPeek', PEEK + 'px');
    root.classList.add('rUI');
    if (mob()) setOpen(false);

    const relayout = () => {
      if (S.z === 1) { dispatchEvent(new Event('resize')); return; }   // the original resize handler rebuilds the map
      layout();
      if (S.z === 0 && !anim) { S.k = G.k * gz; S.c = [...G.c]; }
      kick();
    };
    relayout();
    document.fonts?.ready?.then(relayout);
    mq.addEventListener?.('change', () => { syncMode(); relayout(); });

    /* ---------- 5. Phone: pinch to zoom, tap to see info ---------- */
    const pts = new Map();
    let pinch = null, hadPinch = false, tap = null;
    const two = () => { const [a, b] = [...pts.values()]; return { d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, m: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] }; };

    map.addEventListener('pointerdown', e => {
      if (e.pointerType !== 'touch') return;
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      if (pts.size === 1) { hadPinch = false; tap = [e.clientX, e.clientY]; hideTip(); }
      if (pts.size === 2 && !anim && (S.z === 0 || S.z === 1)) {
        pinch = two(); hadPinch = true; tap = null;
        drag = null; dragging = false; map.classList.remove('grabbing'); hideTip();
        e.stopImmediatePropagation();          // do not let the original code start a drag with the 2nd finger
      }
    }, { capture: true });

    map.addEventListener('pointermove', e => {
      if (e.pointerType !== 'touch' || !pts.has(e.pointerId)) return;
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      if (!pinch || pts.size < 2) return;
      const n = two(), f = n.d / pinch.d;
      if (S.z === 1) {
        zoomBy(n.m[0], n.m[1], f);
        Zt.x += n.m[0] - pinch.m[0]; Zt.y += n.m[1] - pinch.m[1]; clampZ(Zt);
      } else if (S.z === 0) {
        gz = clamp(gz * f, .55, 3.2); S.k = G.k * gz;
      }
      pinch = n; kick();
      e.stopImmediatePropagation();
    }, { capture: true });

    const endTouch = e => {
      if (e.pointerType !== 'touch') return;
      pts.delete(e.pointerId);
      if (hadPinch) {
        if (pts.size < 2) pinch = null;
        drag = null; dragging = false; map.classList.remove('grabbing'); kick();
        e.stopImmediatePropagation();          // pinch is not a tap
        if (pts.size === 0) hadPinch = false;
        return;
      }
      // Tap (barely moved): show the tooltip like a mouse hover would
      if (e.type === 'pointerup' && tap && S.z === 1 && !patrolMode &&
          Math.hypot(e.clientX - tap[0], e.clientY - tap[1]) < 8) {
        const x = e.clientX, y = e.clientY;
        setTimeout(() => map.dispatchEvent(new PointerEvent('pointermove', { clientX: x, clientY: y, pointerType: 'mouse', bubbles: true })), 30);
      }
      tap = null;
    };
    map.addEventListener('pointerup', endTouch, { capture: true });
    map.addEventListener('pointercancel', endTouch, { capture: true });

    console.info('[responsive] module on');
  } catch (err) {
    // On any error: remove the flag class so the CSS stops applying
    console.error('[responsive] error, back to the original layout', err);
    document.documentElement.classList.remove('rUI', 'rMob');
  }
})();
