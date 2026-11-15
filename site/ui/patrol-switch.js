/* =====================================================================
   ui/patrol-switch.js  —  Instant province switching on the patrol map
   Team 268LTK · NASA Space Apps 2026

   Old problem: when switching province on the patrol map,
     (1) the map started zooming BEFORE the new province's data had loaded,
         so the old province's image got stretched along with the zoom;
     (2) once the new data arrived, the old image faded out over ~1 s
         (class "hl out"), leaving a "ghost" of the old province that lagged,
         especially on phones.
   Fix (index.html's original code is NOT changed):
     - load the new province's data first, then switch;
     - in patrol mode the old layer disappears immediately (no fade);
     - the map jumps straight to the new province (no zoom animation).
       Want a smooth zoom back? Set ANIMATE_ZOOM = true.
   The fire map (non-patrol) keeps its original fade effect.

   Load order: AFTER the main <script> in index.html.
   Remove the module: delete the line containing "ui/patrol-switch.js" in index.html.
   ===================================================================== */
(function () {
  'use strict';
  const ANIMATE_ZOOM = false;
  try {
    if (typeof selectPatrolProv !== 'function' || typeof swapHeat !== 'function') {
      console.warn('[patrol-switch] main script not found, module disabled');
      return;
    }

    /* 1. Switch layers instantly in patrol mode */
    const origSwap = swapHeat;
    swapHeat = function (instant) {
      if (!patrolMode) return origSwap(instant);           // fire map: keep the original fade
      const cur = heat[hi], nx = heat[1 - hi];
      renderHeat(nx); heatBox.style.transform = '';
      cur.style.transition = nx.style.transition = 'none';
      nx.className = 'hl on';  nx.style.zIndex = 2;
      cur.className = 'hl pre'; cur.style.zIndex = 1;      // hide the old layer right away
      void nx.offsetWidth;                                 // apply now, then restore the transitions
      cur.style.transition = nx.style.transition = '';
      hi = 1 - hi;
    };

    /* 2. Switch province: load data first, then show it */
    let seq = 0;
    selectPatrolProv = async function (name, useDefMonth = true) {
      if (!PATROL_BY_NAME.has(name)) name = 'Điện Biên';
      const token = ++seq;
      pProvName = name;
      const selEl = document.querySelector('#pProvSel'); if (selEl) selEl.value = name;
      const info = PATROL_BY_NAME.get(name);
      if (useDefMonth) pMonth = info.def;

      if (!PATROL_CACHE.has(info.id)) {
        const rows = await d3.csv(`data/patrol_cells/new_${info.id}.csv`);
        PATROL_CACHE.set(info.id, rows.map(r => ({
          lat: +r.cell_lat, lon: +r.cell_lon, m: +r.month, yrs: +r.n_years_with_fire,
          acc: r.access_class, dist: +r.dist_vehicle_m, slope: +r.slope_mean_deg, pri: r.priority_class
        })));
      }
      if (token !== seq) return;          // the user already picked another province, drop this result

      const idx = provs ? provs.findIndex(f => f.properties.shapeName === name) : -1;
      if (idx >= 0) {
        selP = idx;
        if (S.z === 1 && BB && BB[idx]) {
          fitBox(BB[idx]);
          if (!ANIMATE_ZOOM) { Z = { ...Zt }; terrainDirty = true; }   // jump straight there
        }
      }
      patrolSel = null; patrolHover = null;
      document.querySelector('#patrolCard')?.classList.remove('show');
      hideTip();
      updatePatrolUI();                   // calls swapHeat(true): draws the new province once, at the final position
      kick();
    };

    console.info('[patrol-switch] module on');
  } catch (err) {
    console.error('[patrol-switch] error, keeping the original behaviour', err);
  }
})();
