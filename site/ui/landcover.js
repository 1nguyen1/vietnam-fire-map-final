/* =====================================================================
   ui/landcover.js  —  Filter hotspots by land cover (Forest / Cropland / Other)
   Team 268LTK · NASA Space Apps 2026

   Data (created by pipeline/landcover.py, in data/landcover/):
     lc_grid.bin.gz            0.01° label grid (ESA WorldCover 2021, checked against MODIS MCD12Q1)
     lc_meta.json              grid description
     lc_override.json          per year: cells whose land changed (according to NASA MODIS MCD12Q1)
     province_monthly_lc.json  forest / cropland share by province × month

   What it does (index.html's original code is NOT changed):
     - Settings gets "Land cover: All / Forest / Cropland / Other".
     - Filters EVERYTHING in step: hotspot map (heat, 1 km grid, daily points),
       totals, province ranking, Calendar & Charts window, Compare tab, patrol map.
       Monthly numbers = harmonized number × that land type's share in the province that month.
     - Tooltip and patrol card get a line "Land cover: …" (with "land converted" /
       "uncertain" warnings where they apply).
     - "All" = exactly like the original web.

   Load order: AFTER the main <script> (after the other ui/*.js modules if present).
   Remove the module: delete the line containing "ui/landcover.js" in index.html.
   ===================================================================== */
(function () {
  'use strict';
  try {
    const need = ['update', 'calcMax', 'applyLang', 'showTip', 'showPatrolCard', 'periodNote', 'renderAnalytics', 'updatePatrolUI'];
    if (need.some(n => typeof window[n] !== 'function') || typeof CELLS === 'undefined' || typeof DAYS === 'undefined' || typeof NAT === 'undefined') {
      console.warn('[landcover] main script not found, module disabled');
      return;
    }
    const q = s => document.querySelector(s), qa = s => [...document.querySelectorAll(s)];
    const BASE = 'data/landcover/';

    /* ---------- Text ---------- */
    const TX = {
      vi: {
        set: 'Lớp phủ đất', all: 'Tất cả', forest: 'Rừng', agri: 'Nông nghiệp', other: 'Khác',
        lab: { 0: 'khác (cây bụi, cỏ, đất trống…)', 1: 'rừng', 2: 'nông nghiệp', 3: 'hỗn hợp / không chắc' },
        tip: 'Lớp phủ', tree: 'cây gỗ', crop: 'trồng trọt',
        unc: '⚠ ESA và MODIS không thống nhất', chg: (y, a, b) => `⚠ Năm ${y} là ${a} (MODIS), nay là ${b}`,
        note: { forest: 'Chỉ cháy trong rừng', agri: 'Chỉ đốt nông nghiệp', other: 'Chỉ đất khác / hỗn hợp' },
        noteTail: 'ước tính theo lớp phủ đất (ESA WorldCover + NASA MCD12Q1)',
        loading: 'Đang tải lớp phủ đất…', fail: 'Không tải được dữ liệu lớp phủ đất'
      },
      en: {
        set: 'Land cover', all: 'All', forest: 'Forest', agri: 'Cropland', other: 'Other',
        lab: { 0: 'other (shrub, grass, bare…)', 1: 'forest', 2: 'cropland', 3: 'mixed / uncertain' },
        tip: 'Land cover', tree: 'trees', crop: 'crops',
        unc: '⚠ ESA and MODIS disagree', chg: (y, a, b) => `⚠ ${a} in ${y} (MODIS), ${b} now`,
        note: { forest: 'Forest fires only', agri: 'Cropland burning only', other: 'Other / mixed land only' },
        noteTail: 'estimated from land cover (ESA WorldCover + NASA MCD12Q1)',
        loading: 'Loading land cover…', fail: 'Could not load land-cover data'
      }
    };
    const tx = () => TX[lang === 'vi' ? 'vi' : 'en'];

    /* ---------- Load data ---------- */
    let LC = null, F = 'all', loadP = null;
    function loadLC() {
      if (loadP) return loadP;
      loadP = Promise.all([
        d3.json(BASE + 'lc_meta.json'),
        fetch(BASE + 'lc_grid.bin.gz').then(r => { if (!r.ok) throw new Error(r.status); return r.arrayBuffer(); }).then(gunzipBuf),
        d3.json(BASE + 'lc_override.json'),
        d3.json(BASE + 'province_monthly_lc.json')
      ]).then(([meta, buf, ov, share]) => {
        const g = new Uint8Array(buf), N = meta.w * meta.h, ovr = new Map();
        for (const [y, a] of Object.entries(ov)) { const m = new Map(); for (let i = 0; i < a.length; i += 3) m.set(CK(a[i], a[i + 1]), a[i + 2]); ovr.set(+y, m); }
        LC = { meta, cls: g.subarray(0, N), fp: g.subarray(N, 2 * N), cp: g.subarray(2 * N, 3 * N), flag: g.subarray(3 * N, 4 * N), ovr, share };
      });
      return loadP;
    }
    const idxOf = (a, o) => {
      const m = LC.meta, r = Math.floor((m.y0 - (a + .5) * .01) / m.d), c = Math.floor(((o + .5) * .01 - m.x0) / m.d);
      return r < 0 || c < 0 || r >= m.h || c >= m.w ? -1 : r * m.w + c;
    };
    function labelAt(a, o, y) {                  // y = fire year (null = current state, for the patrol map)
      if (y != null) { const v = LC.ovr.get(y)?.get(CK(a, o)); if (v !== undefined) return v; }
      const k = idxOf(a, o); return k < 0 ? 0 : LC.cls[k];
    }
    const match = l => F === 'forest' ? l === 1 : F === 'agri' ? l === 2 : (l === 0 || l === 3);
    const shareOf = s => !s ? null : F === 'forest' ? s[0] : F === 'agri' ? s[1] : Math.max(0, 1 - s[0] - s[1]);

    /* ---------- Filter monthly numbers (PV, NAT) ---------- */
    let PV0 = null, NAT0 = null;
    function applyNumbers() {
      if (!PV0 && PV) PV0 = PV;
      if (!NAT0) NAT0 = new Map([...NAT].map(([k, v]) => [k, { ...v }]));
      if (F === 'all' || !LC) {
        if (PV0) PV = PV0;
        NAT0.forEach((v, k) => NAT.set(k, { ...v }));
      } else {
        const VN = LC.share.VN || {};
        if (PV0 && PROVD) {
          PV = PV0.map((row, k) => {
            const ym = PROVD.months[k];
            return Float64Array.from(row, (v, i) => {
              if (!v) return 0;
              const s = shareOf(LC.share[provs[i].properties.id]?.[ym]) ?? shareOf(VN[ym]) ?? 0;
              return v * s;
            });
          });
        }
        NAT0.forEach((v, k) => {
          const y = Math.floor((k - 1) / 12), m = k - y * 12, s = shareOf(VN[`${y}-${p2(m)}`]) ?? 0;
          NAT.set(k, { ...v, h: v.h * s, cl: v.cl * s, ch: v.ch * s, ra: v.ra * s, rt: v.rt * s, rv: v.rv * s, rn: v.rn * s });
        });
      }
      calcMax();
    }

    /* ---------- Filter 1 km cells, daily points, patrol cells (patched getters) ---------- */
    const memo = new WeakMap();
    const cached = (raw, make) => { let c = memo.get(raw); if (!c) memo.set(raw, c = {}); return c[F] || (c[F] = make()); };
    const cellsGet = CELLS.get.bind(CELLS);
    CELLS.get = function (y) {
      const v = cellsGet(y);
      if (F === 'all' || !LC || !v || typeof v !== 'object') return v;
      return cached(v, () => { const o = {}; for (const [mm, rows] of Object.entries(v)) o[mm] = rows.filter(r => match(labelAt(r[0], r[1], y))); return o; });
    };
    const daysGet = DAYS.get.bind(DAYS);
    DAYS.get = function (y) {
      const D = daysGet(y);
      if (F === 'all' || !LC || !D || typeof D !== 'object' || !D.n) return D;
      return cached(D, () => {
        const keep = [];
        for (let i = 0; i < D.n; i++) {
          const a = Math.floor((D.la[i] / 4000 + 8) / .01), o = Math.floor((D.lo[i] / 4000 + 102) / .01);
          if (match(labelAt(a, o, y))) keep.push(i);
        }
        const pick = (A, T) => T.from(keep, i => A[i]);
        return { n: keep.length, t: pick(D.t, Uint32Array), la: pick(D.la, Uint16Array), lo: pick(D.lo, Uint16Array), fr: pick(D.fr, Uint16Array), pi: pick(D.pi, Uint8Array), sc: pick(D.sc, Uint8Array) };
      });
    };
    const patGet = PATROL_CACHE.get.bind(PATROL_CACHE);
    PATROL_CACHE.get = function (id) {
      const rows = patGet(id);
      if (F === 'all' || !LC || !Array.isArray(rows)) return rows;
      return cached(rows, () => rows.filter(r => match(labelAt(Math.floor(r.lat / .01), Math.floor(r.lon / .01), null))));
    };

    /* ---------- Notes: legend, panel, Calendar & Charts window ---------- */
    const ORIG = { vi: { legend: T.vi.legend, patrolTitle: T.vi.patrolTitle }, en: { legend: T.en.legend, patrolTitle: T.en.patrolTitle } };
    function setLegendText() {
      ['vi', 'en'].forEach(l => {
        const suf = F === 'all' ? '' : ' · ' + TX[l][F];
        T[l].legend = ORIG[l].legend + suf; T[l].patrolTitle = ORIG[l].patrolTitle + suf;
      });
    }
    const origNote = periodNote;
    periodNote = function () {
      const s = origNote();
      return F === 'all' ? s : `${s ? s + ' · ' : ''}<span style="color:#9ccc65">${tx().note[F]}</span> · ${tx().noteTail}`;
    };
    const origRA = renderAnalytics;
    renderAnalytics = function () {
      origRA();
      if (F !== 'all') q('#anaBody')?.insertAdjacentHTML('afterbegin',
        `<div style="font-size:12px;padding:8px 12px;border-radius:10px;background:rgba(156,204,101,.12);color:#c5e1a5">${tx().note[F]} · ${tx().noteTail}</div>`);
    };

    /* ---------- Tooltip + patrol card ---------- */
    function lcLine(a, o, y) {
      if (!LC) return '';
      const k = idxOf(a, o); if (k < 0) return '';
      const t = tx(), base = LC.cls[k], ov = y != null ? LC.ovr.get(y)?.get(CK(a, o)) : undefined, lbl = ov ?? base;
      let s = `${t.tip}: <i style="font-style:normal;font-weight:600;color:#dcedc8">${t.lab[lbl]}</i> · ${t.tree} ${LC.fp[k]}% · ${t.crop} ${LC.cp[k]}%`;
      if (ov !== undefined) s += `<br>${t.chg(y, t.lab[ov], t.lab[base])}`;
      else if (LC.flag[k] === 2) s += `<br>${t.unc}`;
      return s;
    }
    const origTip = showTip;
    showTip = function () {
      origTip();
      if (!LC || tip.style.opacity === '0') return;
      let line = '';
      if (patrolMode && patrolHover) line = lcLine(Math.floor(patrolHover.lat / .01), Math.floor(patrolHover.lon / .01), null);
      else if (!patrolMode && hc >= 0 && CUR?.has(hc)) line = lcLine(Math.floor(hc / 100000), hc % 100000, sel.y);
      if (!line) return;
      tip.insertAdjacentHTML('beforeend', `<span style="display:block;margin-top:4px;color:#c5e1a5">${line}</span>`);
      const r = tip.getBoundingClientRect(), x = clamp(mouse[0] + 16, 8, V.w - r.width - 8), y = clamp(mouse[1] - r.height - 14, 8, V.h - r.height - 8);
      tip.style.transform = `translate(${x}px,${y}px)`;
    };
    const origCard = showPatrolCard;
    showPatrolCard = function (r) {
      origCard(r);
      if (!r || !LC) return;
      const line = lcLine(Math.floor(r.lat / .01), Math.floor(r.lon / .01), null);
      q('#patrolCard > div')?.insertAdjacentHTML('beforeend', `<br><span style="color:#c5e1a5">${line}</span>`);
    };

    /* ---------- Settings UI ---------- */
    Object.assign(T.vi, { setLc: TX.vi.set, lcAll: TX.vi.all, lcForest: TX.vi.forest, lcAgri: TX.vi.agri, lcOther: TX.vi.other });
    Object.assign(T.en, { setLc: TX.en.set, lcAll: TX.en.all, lcForest: TX.en.forest, lcAgri: TX.en.agri, lcOther: TX.en.other });
    const pop = q('#settingsPop');
    const grp = document.createElement('div');
    grp.className = 'setGrp';
    grp.innerHTML = '<div class="lab" data-i="setLc"></div><div class="seg" id="lcSeg">' +
      '<button data-lc="all" data-i="lcAll"></button><button data-lc="forest" data-i="lcForest"></button>' +
      '<button data-lc="agri" data-i="lcAgri"></button><button data-lc="other" data-i="lcOther"></button></div>' +
      '<div id="lcMsg" style="font-size:11px;color:var(--dim);display:none"></div>';
    pop?.insertBefore(grp, pop.firstChild);
    const st = document.createElement('style');
    st.textContent = '#lcSeg{display:flex}#lcSeg button{flex:1 1 auto;padding:0 6px;font-size:11.5px;white-space:nowrap}';
    document.head.appendChild(st);
    grp.querySelectorAll('[data-i]').forEach(e => { e.textContent = L()[e.dataset.i]; });
    const mark = () => qa('#lcSeg button').forEach(b => b.classList.toggle('act', b.dataset.lc === F));
    mark();

    async function setFilter(v) {
      if (v === F) return;
      const msg = q('#lcMsg');
      if (v !== 'all' && !LC) {
        msg.style.display = ''; msg.textContent = tx().loading;
        try { await loadLC(); } catch (e) { console.error('[landcover]', e); msg.textContent = tx().fail; loadP = null; return; }
        msg.style.display = 'none';
      }
      F = v; mark();
      setLegendText();
      applyNumbers();
      hc = -1; patrolSel = null; q('#patrolCard')?.classList.remove('show');
      applyLang();
      if (provs) update(S.z === 1);
      if (q('#anaModal')?.classList.contains('open')) renderAnalytics();
    }
    q('#lcSeg').addEventListener('click', e => { const v = e.target.closest('button')?.dataset.lc; if (v) setFilter(v); });

    // Load the data in the background (small) so tooltips can show land cover even in "All" mode
    setTimeout(() => loadLC().catch(e => console.warn('[landcover] data not loaded yet', e)), 1500);

    console.info('[landcover] module on');
  } catch (err) {
    console.error('[landcover] error, module disabled', err);
  }
})();
