/* =====================================================================
   ui/transitions.js  —  Province-switch transitions
                         (fire calendar + patrol map)
   Team 268LTK · NASA Space Apps 2026

   REPLACES ui/patrol-switch.js (this file already includes all of it).
   Only the transition effects change; button layout is untouched.

   Effects:
     [3] Fly to the new province (~0.35–0.6 s). The hotspot layer is hidden
         during the flight and fades back in, sharp, on arrival (no more
         blurry stretched image).
     [5] Spotlight: the other provinces are dimmed so the selected one stands out.
     [6] Glowing border pulse around the province on arrival.
     [7] Patrol map: cells appear by priority, Low → Medium → High.
     [8] Patrol map: the High / Medium / Low counters count up to the new value.
     [9] Patrol map: load data first, show a spinner while loading;
         on a computer, hovering a province pre-loads its data.
    [10] Settings gets "Transitions: Smooth / Fast / Off". If the device has
         "reduce motion" turned on, the default is "Fast". The choice is saved
         for the next visit.
   Plus: in patrol mode the old province's layer disappears at once (no ghost fade).

   Load order: AFTER the main <script> (and after ui/responsive.js if it is there).
   Remove the module: delete the line containing "ui/transitions.js" in index.html.
   ===================================================================== */
(function () {
  'use strict';
  try {
    const need = ['frame', 'draw', 'fitBox', 'resetView', 'swapHeat', 'renderHeat', 'selectPatrolProv', 'updatePatrolUI'];
    if (need.some(n => typeof window[n] !== 'function') || typeof Z === 'undefined') {
      console.warn('[transitions] main script not found, module disabled');
      return;
    }
    const q = s => document.querySelector(s), qa = s => [...document.querySelectorAll(s)];

    /* ---------- [10] Mode: smooth / fast / off ---------- */
    const KEY = 'fx268';
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    let FX = (() => { try { return localStorage.getItem(KEY); } catch (e) { return null; } })() || (reduce ? 'fast' : 'smooth');
    if (!['smooth', 'fast', 'off'].includes(FX)) FX = 'smooth';
    const smooth = () => FX === 'smooth';

    Object.assign(T.vi, { setFx: 'Hiệu ứng chuyển cảnh', fxSmooth: 'Mượt', fxFast: 'Nhanh', fxOff: 'Tắt' });
    Object.assign(T.en, { setFx: 'Transitions', fxSmooth: 'Smooth', fxFast: 'Fast', fxOff: 'Off' });
    const pop = q('#settingsPop');
    if (pop) {
      const grp = document.createElement('div');
      grp.className = 'setGrp';
      grp.innerHTML = '<div class="lab" data-i="setFx"></div><div class="seg" id="fxSeg">' +
        '<button data-fx="smooth" data-i="fxSmooth"></button><button data-fx="fast" data-i="fxFast"></button><button data-fx="off" data-i="fxOff"></button></div>';
      pop.appendChild(grp);
      grp.querySelectorAll('[data-i]').forEach(e => { e.textContent = L()[e.dataset.i]; });
      const mark = () => qa('#fxSeg button').forEach(b => b.classList.toggle('act', b.dataset.fx === FX));
      mark();
      q('#fxSeg').addEventListener('click', e => {
        const v = e.target.closest('button')?.dataset.fx; if (!v) return;
        FX = v; mark();
        try { localStorage.setItem(KEY, v); } catch (err) { }
        if (!smooth()) { cancelFly(); REVEAL = null; PULSE = null; }
        kick();
      });
    }

    /* ---------- CSS for the spinner (injected, no layout change) ---------- */
    const st = document.createElement('style');
    st.textContent = '#patrolBox{position:relative}' +
      '#rSpin{position:absolute;width:14px;height:14px;border:2px solid rgba(230,213,176,.25);border-top-color:#f08a34;border-radius:50%;' +
      'animation:rSpin .7s linear infinite;pointer-events:none;display:none;z-index:2}#rSpin.on{display:block}' +
      '#pProvSel.rLoading{opacity:.7;cursor:progress}@keyframes rSpin{to{transform:rotate(360deg)}}';
    document.head.appendChild(st);

    /* ---------- show / hide the hotspot layer ---------- */
    let showT = 0;
    const hideHeat = () => { clearTimeout(showT); heatBox.style.transition = 'opacity .12s ease'; heatBox.style.opacity = '0'; };
    const clearHeatStyle = () => { heatBox.style.opacity = ''; heatBox.style.transition = ''; };
    const showHeat = fade => {
      clearTimeout(showT);
      if (!fade) { clearHeatStyle(); return; }
      heatBox.style.transition = 'opacity .2s ease'; heatBox.style.opacity = '1';
      showT = setTimeout(() => { if (!FLY) clearHeatStyle(); }, 260);
    };

    /* ---------- [3] Fly between provinces ---------- */
    let FLY = null;
    function cancelFly() {
      if (!FLY) return;
      FLY = null; Zt = { ...Z }; tau = 70; clearHeatStyle(); kick();
    }
    function startFly(to) {
      cancelFly();
      const same = Math.abs(to.s - Z.s) < 1e-3 && Math.abs(to.x - Z.x) < 1 && Math.abs(to.y - Z.y) < 1;
      if (!smooth() || S.z !== 1 || anim || same) {             // Fast / Off: jump straight there
        Z = { ...to }; Zt = { ...to }; tau = 70; terrainDirty = true; kick();
        arrive(false);
        return;
      }
      const RW = Math.max(1, R.x1 - R.x0), P = [(R.x0 + R.x1) / 2, (R.y0 + R.y1) / 2];
      const b = z => [(P[0] - z.x) / z.s, (P[1] - z.y) / z.s, RW / z.s];
      const i = d3.interpolateZoom.rho(1)(b(Z), b(to));
      FLY = { i, to, RW, P, t0: performance.now(), dur: clamp(i.duration * .5, 350, 600) };
      hideHeat(); hideTip();
      Zt = { ...to }; tau = 1e9; kick();
    }
    function arrive(anim2) {
      showHeat(anim2);
      if (anim2 && patrolMode) startReveal();
      if (anim2 && selP >= 0) { PULSE = { idx: selP, t0: performance.now() }; loop(); }
    }

    // fitBox / resetView: same zoom target as the original, but flown there
    fitBox = function (bb) {
      const [[x0, y0], [x1, y1]] = bb, s = clamp(Math.min((R.x1 - R.x0) / (x1 - x0), (R.y1 - R.y0) / (y1 - y0)) * .7, 1.4, 10);
      startFly(clampZ({ s, x: (R.x0 + R.x1) / 2 - (x0 + x1) / 2 * s, y: (R.y0 + R.y1) / 2 - (y0 + y1) / 2 * s }));
    };
    resetView = function () { selP = -1; startFly({ s: 1, x: 0, y: 0 }); };
    const fitBtn = q('#fit'); if (fitBtn) fitBtn.onclick = () => resetView();

    // Animation loop: interpolate Z each frame; the original frame() keeps doing the rest
    const origFrame = frame;
    frame = function (now) {
      let arrived = false;
      if (FLY) {
        if (anim || S.z !== 1) { FLY = null; tau = 70; clearHeatStyle(); }
        else {
          const t = Math.min(1, (now - FLY.t0) / FLY.dur), v = FLY.i(d3.easeCubicInOut(t)), s = FLY.RW / v[2];
          if (t >= 1) { Z = { ...FLY.to }; Zt = { ...FLY.to }; tau = 70; FLY = null; arrived = true; }
          else { Z = { s, x: FLY.P[0] - v[0] * s, y: FLY.P[1] - v[1] * s }; Zt = { ...FLY.to }; tau = 1e9; }
        }
      }
      const r = origFrame(now);
      if (FLY) kick();                  // keep frames coming until the flight is over
      if (arrived) arrive(true);
      return r;
    };
    // No tooltip while flying (it would sit at a stale position)
    const origShowTip = showTip;
    showTip = function () { if (FLY) return hideTip(); return origShowTip(); };
    // The user touching / scrolling the map stops the flight
    const map = q('#map');
    map.addEventListener('pointerdown', cancelFly, { capture: true });
    map.addEventListener('wheel', cancelFly, { capture: true, passive: true });
    addEventListener('resize', () => { if (FLY) { FLY = null; tau = 70; clearHeatStyle(); } });

    /* ---------- [5] Spotlight + [6] Border pulse (drawn on the map canvas) ---------- */
    let SPOT = { idx: -1, t0: 0 }, PULSE = null, looping = false;
    function loop() {                  // keep drawing while an effect is running (map only, light)
      if (looping) return; looping = true;
      (function tick() {
        const now = performance.now();
        const busy = (PULSE && now - PULSE.t0 < 700) || (SPOT.idx >= 0 && now - SPOT.t0 < 340);
        if (!running) draw(now);
        if (busy) requestAnimationFrame(tick); else looping = false;
      })();
    }
    const origDraw = draw;
    draw = function (now = performance.now()) {
      origDraw(now);
      if (FX === 'off' || S.z !== 1 || !P2D || anim) return;
      const idx = selP;
      if (idx !== SPOT.idx) { SPOT = { idx, t0: now }; if (idx >= 0 && smooth()) loop(); }
      if (idx < 0 || !P2D[idx]) return;
      ctx.save();
      ctx.setTransform(DPR * Z.s, 0, 0, DPR * Z.s, DPR * Z.x, DPR * Z.y);
      const a = (smooth() ? sm((now - SPOT.t0) / 320) : 1) * (mapTheme === 'terrain' ? .5 : .55);
      if (a > .004) {
        const p = new Path2D();
        p.rect(-Z.x / Z.s - 20, -Z.y / Z.s - 20, V.w / Z.s + 40, V.h / Z.s + 40);
        p.addPath(P2D[idx]);
        ctx.fillStyle = `rgba(4,9,26,${a})`; ctx.fill(p, 'evenodd');
        ctx.strokeStyle = '#fff'; ctx.lineWidth = 2.2 / Z.s; ctx.stroke(P2D[idx]);
      }
      if (PULSE && PULSE.idx === idx) {
        const t = (now - PULSE.t0) / 700;
        if (t >= 1) PULSE = null;
        else {
          ctx.strokeStyle = `rgba(255,196,120,${(1 - t) * .9})`; ctx.lineWidth = (2 + 7 * t) / Z.s;
          ctx.shadowColor = 'rgba(255,160,80,.9)'; ctx.shadowBlur = 14 * (1 - t);
          ctx.stroke(P2D[idx]);
        }
      }
      ctx.restore();
    };

    /* ---------- Patrol: instant layer switch (from patrol-switch.js) ---------- */
    const origSwap = swapHeat;
    swapHeat = function (instant) {
      if (!patrolMode) return origSwap(instant);           // fire map: keep the original fade
      const cur = heat[hi], nx = heat[1 - hi];
      renderHeat(nx); heatBox.style.transform = '';
      cur.style.transition = nx.style.transition = 'none';
      nx.className = 'hl on'; nx.style.zIndex = 2;
      cur.className = 'hl pre'; cur.style.zIndex = 1;
      void nx.offsetWidth;
      cur.style.transition = nx.style.transition = '';
      hi = 1 - hi;
    };

    /* ---------- [7] Cells appear by priority ---------- */
    let REVEAL = null, revTok = 0;
    const ORD = { low: 0, medium: 1, high: 2 };
    const origRender = renderHeat;
    renderHeat = function (cv) {
      if (!patrolMode || !REVEAL) return origRender(cv);
      const c = cv.getContext('2d'); c.setTransform(DPR, 0, 0, DPR, 0, 0); c.clearRect(0, 0, V.w, V.h); Zr = { ...Z }; if (!P2D) return;
      c.setTransform(DPR * Z.s, 0, 0, DPR * Z.s, DPR * Z.x, DPR * Z.y);
      c.fillStyle = mapTheme === 'terrain' ? 'rgba(255,255,255,.04)' : `rgba(${BEIGE},.03)`; P2D.forEach(p => c.fill(p));
      const sz = Math.max(cellPx, 2.2 / Z.s), half = sz / 2, lvl = REVEAL.lvl;
      const rows = pRows.filter(r => (ORD[r.pri] ?? 0) <= lvl).sort((a, b) => ORD[a.pri] - ORD[b.pri]);
      for (const r of rows) { const p = proj([r.lon, r.lat]); if (!p) continue; c.fillStyle = PCOL[r.pri] || '#f2c063'; c.fillRect(p[0] - half, p[1] - half, sz, sz); }
    };
    function startReveal() {
      if (!patrolMode || S.z !== 1 || !smooth()) return;
      const tok = ++revTok, step = (lvl, ms) => setTimeout(() => {
        if (tok !== revTok || !patrolMode) return;
        REVEAL = lvl < 2 ? { lvl } : null; renderHeat(heat[hi]);
      }, ms);
      REVEAL = { lvl: 0 }; renderHeat(heat[hi]);
      step(1, 110); step(2, 220);
    }

    /* ---------- [8] Counter count-up + reveal when month / province changes ---------- */
    let lastKey = '';
    const origUPU = updatePatrolUI;
    updatePatrolUI = function () {
      const old = qa('#pStats b').map(b => +b.textContent || 0);
      origUPU();
      const key = `${pProvName}|${pMonth}|${pHardOnly}`, changed = key !== lastKey; lastKey = key;
      if (!changed || !smooth()) return;
      qa('#pStats b').forEach((b, k) => {
        const to = +b.textContent || 0, from = old[k] ?? 0; if (from === to) return;
        const t0 = performance.now();
        (function tick(n) {
          const t = Math.min(1, (n - t0) / 450); b.textContent = Math.round(from + (to - from) * d3.easeCubicOut(t));
          if (t < 1 && b.isConnected) requestAnimationFrame(tick);
        })(t0);
      });
      if (!FLY && S.z === 1 && patrolMode) startReveal();
    };

    /* ---------- [9] Load patrol data first, with a spinner ---------- */
    const PEND = new Map();
    function loadPatrol(id) {
      if (PATROL_CACHE.has(id)) return Promise.resolve();
      if (PEND.has(id)) return PEND.get(id);
      const pr = d3.csv(`data/patrol_cells/new_${id}.csv`).then(rows => {
        PATROL_CACHE.set(id, rows.map(r => ({
          lat: +r.cell_lat, lon: +r.cell_lon, m: +r.month, yrs: +r.n_years_with_fire,
          acc: r.access_class, dist: +r.dist_vehicle_m, slope: +r.slope_mean_deg, pri: r.priority_class
        })));
      }).finally(() => PEND.delete(id));
      PEND.set(id, pr); return pr;
    }
    const selEl = q('#pProvSel');
    const spin = document.createElement('span'); spin.id = 'rSpin';
    q('#patrolBox')?.appendChild(spin);
    function spinner(on) {
      if (!selEl) return;
      selEl.classList.toggle('rLoading', on);
      if (on) { spin.style.top = (selEl.offsetTop + (selEl.offsetHeight - 14) / 2) + 'px'; spin.style.left = (selEl.offsetLeft + selEl.offsetWidth - 46) + 'px'; }
      spin.classList.toggle('on', on);
    }
    let seq = 0;
    selectPatrolProv = async function (name, useDefMonth = true) {
      if (!PATROL_BY_NAME.has(name)) name = 'Điện Biên';
      const token = ++seq;
      pProvName = name; if (selEl) selEl.value = name;
      const info = PATROL_BY_NAME.get(name);
      if (useDefMonth) pMonth = info.def;
      if (!PATROL_CACHE.has(info.id)) {
        spinner(true);
        try { await loadPatrol(info.id); }
        catch (e) { console.error('[transitions] could not load data for province', name, e); if (token === seq) spinner(false); return; }
        if (token === seq) spinner(false);
      }
      if (token !== seq) return;                       // the user already picked another province
      const idx = provs ? provs.findIndex(f => f.properties.shapeName === name) : -1;
      if (idx >= 0) { selP = idx; if (S.z === 1 && BB && BB[idx]) fitBox(BB[idx]); }
      patrolSel = null; patrolHover = null;
      q('#patrolCard')?.classList.remove('show');
      hideTip();
      updatePatrolUI();
      kick();
    };
    // Computer: hover over a province for 0.25 s = pre-load its data
    let hovT = 0, hovI = -1;
    map.addEventListener('pointermove', e => {
      if (e.pointerType !== 'mouse' || !patrolMode || S.z !== 1) return;
      if (hover === hovI) return; hovI = hover; clearTimeout(hovT);
      if (hover < 0 || !provs[hover]) return;
      const info = PATROL_BY_NAME.get(provs[hover].properties.shapeName);
      if (info && !PATROL_CACHE.has(info.id)) hovT = setTimeout(() => loadPatrol(info.id).catch(() => { }), 250);
    });

    console.info('[transitions] module on · mode:', FX);
  } catch (err) {
    console.error('[transitions] error, keeping the original behaviour', err);
  }
})();
