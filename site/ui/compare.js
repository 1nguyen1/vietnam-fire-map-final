/* =====================================================================
   ui/compare.js  —  "Compare" tab in the Calendar & Charts window
   Team 268LTK · NASA Space Apps 2026

   What it does (index.html's original code is NOT changed):
     - Pick a province (or the whole country) and a date range (from–to)
       → fire chart + fire calendar for that range.
     - Optionally compare with:
         · the SAME province over ANOTHER period (default: same period a year earlier), or
         · ANOTHER province over any period.
     - Summary cards: totals, % difference, peak day/month, mean.
     - Download CSV (data for both series) and PNG (chart, calendar).

   Time resolution (automatic):
     - Range ≤ 366 days → BY DAY. From 02/2012 these are observed VIIRS S-NPP points
       (the harmonized scale). Before that they are Aqua points multiplied by the
       monthly conversion factor (estimate, flagged with ≈).
     - Range > 366 days → BY MONTH, harmonized scale (province_monthly). Months
       only partly inside the range still count as whole months (flagged with *).

   Load order: AFTER the main <script> in index.html.
   Remove the module: delete the line containing "ui/compare.js" in index.html.
   ===================================================================== */
(function () {
  'use strict';
  try {
    if (typeof renderAnalytics !== 'function' || typeof anaTab === 'undefined' || !document.querySelector('#anaTabs')) {
      console.warn('[compare] main script not found, module disabled');
      return;
    }
    const q = s => document.querySelector(s), qa = s => [...document.querySelectorAll(s)];
    const CA = '#f08a34', CB = '#64b5f6';

    /* ---------- Text (vi/en) ---------- */
    Object.assign(T.vi, { tabCmp: 'So sánh khoảng thời gian' });
    Object.assign(T.en, { tabCmp: 'Compare periods' });
    const TX = {
      vi: {
        a: 'Vùng A', b: 'Vùng B (so sánh)', prov: 'Tỉnh / thành', nat: 'Cả nước (Việt Nam)', from: 'Từ ngày', to: 'Đến ngày',
        cmpWith: 'So sánh với', none: 'Không so sánh', time: 'Cùng tỉnh, khoảng khác', other: 'Tỉnh khác',
        loading: 'Đang tải dữ liệu…', total: 'Tổng điểm cháy', diff: 'Chênh lệch A so với B', peakD: 'Ngày cao nhất', peakM: 'Tháng cao nhất',
        avgD: 'Trung bình / ngày', avgM: 'Trung bình / tháng', chart: 'Diễn biến điểm cháy', cal: 'Lịch cháy',
        byDay: 'theo ngày', byMonth: 'theo tháng (thang hài hòa)', csv: '⬇ Tải CSV', png: '⬇ PNG biểu đồ', pngCal: '⬇ PNG lịch',
        noteDay: 'Theo ngày: từ 02/2012 là điểm VIIRS S-NPP đo thật (thang hài hòa); trước đó là điểm MODIS-Aqua nhân hệ số quy đổi của tháng (≈ ước tính).',
        noteMonth: 'Theo tháng: số hài hòa cùng thang VIIRS S-NPP; tháng có dấu * chỉ nằm một phần trong khoảng đã chọn nhưng được tính cả tháng.',
        alignNote: 'Hai chuỗi được xếp theo thứ tự ngày/tháng tính từ ngày bắt đầu của mỗi khoảng.',
        empty: 'Không có dữ liệu trong khoảng đã chọn.', day: 'Ngày', mon: 'Tháng', higher: 'cao hơn', lower: 'thấp hơn'
      },
      en: {
        a: 'Region A', b: 'Region B (comparison)', prov: 'Province', nat: 'National (Vietnam)', from: 'From', to: 'To',
        cmpWith: 'Compare with', none: 'No comparison', time: 'Same province, other period', other: 'Other province',
        loading: 'Loading data…', total: 'Total fire points', diff: 'A vs B', peakD: 'Peak day', peakM: 'Peak month',
        avgD: 'Mean / day', avgM: 'Mean / month', chart: 'Fire activity', cal: 'Fire calendar',
        byDay: 'daily', byMonth: 'monthly (harmonized scale)', csv: '⬇ CSV', png: '⬇ Chart PNG', pngCal: '⬇ Calendar PNG',
        noteDay: 'Daily: from Feb 2012 values are observed VIIRS S-NPP points (harmonized scale); before that, MODIS-Aqua points × that month\'s conversion factor (≈ estimate).',
        noteMonth: 'Monthly: harmonized values on the VIIRS S-NPP scale; months marked * are only partly inside the range but counted in full.',
        alignNote: 'Both series are aligned by day/month number counted from each period\'s start date.',
        empty: 'No data in the selected range.', day: 'Day', mon: 'Month', higher: 'higher', lower: 'lower'
      }
    };
    const tx = k => TX[lang === 'vi' ? 'vi' : 'en'][k];

    /* ---------- Add the tab ---------- */
    const tabBtn = document.createElement('button');
    tabBtn.dataset.tab = 'cmp'; tabBtn.dataset.i = 'tabCmp'; tabBtn.textContent = L().tabCmp;
    q('#anaTabs').appendChild(tabBtn);

    /* ---------- State ---------- */
    const iso = (y, m, d) => `${y}-${p2(m)}-${p2(d)}`;
    const minD = () => iso(Y0, 1, 1), maxD = () => iso(NOW.y, NOW.m, NOW.d);
    const clampD = s => (s < minD() ? minD() : s > maxD() ? maxD() : s);
    const shiftYear = (s, k) => { const [y, m, d] = s.split('-').map(Number); return clampD(iso(y + k, m, Math.min(d, dim(y + k, m)))); };
    let C = null;
    function initState() {
      if (C) return;
      const p = selP >= 0 ? selP : -1;
      const f = clampD(iso(sel.y, sel.m, 1)), t = clampD(iso(sel.y, sel.m, dim(sel.y, sel.m)));
      C = { a: { p, f, t }, mode: 'time', b: { p, f: shiftYear(f, -1), t: shiftYear(t, -1) }, bTouched: false };
    }

    /* ---------- Data ---------- */
    const waitDays = y => new Promise(res => {
      const ok = () => DAYS.has(y) && DAYS.get(y) !== 'loading';
      if (ok()) return res();
      loadDays(y); let n = 0;
      const iv = setInterval(() => { if (ok() || ++n > 300) { clearInterval(iv); res(); } }, 80);
    });
    const parse = s => s.split('-').map(Number);
    const spanDays = (f, t) => Math.round((Date.UTC(...parse(t).map((v, i) => i === 1 ? v - 1 : v)) - Date.UTC(...parse(f).map((v, i) => i === 1 ? v - 1 : v))) / 864e5) + 1;

    async function daily(p, f, t) {
      const [y0, m0, d0] = parse(f), [y1, m1, d1] = parse(t);
      await Promise.all(d3.range(y0, y1 + 1).map(waitDays));
      const out = [], idx = new Map();
      for (let ms = Date.UTC(y0, m0 - 1, d0), end = Date.UTC(y1, m1 - 1, d1); ms <= end; ms += 864e5) {
        const k = new Date(ms).toISOString().slice(0, 10), [y, m] = parse(k);
        const raw = y * 100 + m < 201202, r = natRow(y, m), fac = raw && r && r.ra > 0 ? r.h / r.ra : 1;
        idx.set(k, out.length); out.push({ k, v: 0, fac, est: raw });
      }
      for (let y = y0; y <= y1; y++) {
        const D = DAYS.get(y); if (!D || !D.n) continue;
        const a = (y === y0 ? doy(y0, m0, d0) : 0) * 1440, b = (y === y1 ? doy(y1, m1, d1) + 1 : 400) * 1440;
        for (let i = lowerB(D.t, a), e = lowerB(D.t, b); i < e; i++) {
          if (!(D.sc[i] & 128)) continue;
          if (p >= 0 && PI2P[D.pi[i]] !== p) continue;
          const k = new Date(Date.UTC(y, 0, 1) + Math.floor(D.t[i] / 1440) * 864e5).toISOString().slice(0, 10);
          const j = idx.get(k); if (j !== undefined) out[j].v++;
        }
      }
      out.forEach(o => { o.v = o.v * o.fac; });
      return out;
    }
    function monthly(p, f, t) {
      const [y0, m0, d0] = parse(f), [y1, m1, d1] = parse(t), out = [];
      for (let y = y0, m = m0; y < y1 || (y === y1 && m <= m1); m === 12 ? (y++, m = 1) : m++) {
        const k = mi(y, m), v = p < 0 ? nat(y, m) : (k !== undefined && PV ? PV[k][p] || 0 : 0);
        const part = (y === y0 && m === m0 && d0 > 1) || (y === y1 && m === m1 && d1 < dim(y, m)) || natRow(y, m)?.partial;
        out.push({ k: `${y}-${p2(m)}`, v, part, est: y * 100 + m < 201202 });
      }
      return out;
    }

    /* ---------- Drawing ---------- */
    const pName = p => p < 0 ? tx('nat') : provs[p].properties.shapeName;
    const lblA = () => `A · ${pName(C.a.p)} (${C.a.f} → ${C.a.t})`, lblB = () => `B · ${pName(C.b.p)} (${C.b.f} → ${C.b.t})`;
    const fmtV = v => fmt(v);

    function lineChart(A, B, gran) {
      const W = 920, H = 280, P = { l: 56, r: 16, t: 44, b: 30 }, n = Math.max(A.length, B ? B.length : 0);
      const mx = Math.max(1, d3.max(A, d => d.v), B ? d3.max(B, d => d.v) || 0 : 0);
      const x = d3.scaleLinear().domain([0, Math.max(1, n - 1)]).range([P.l, W - P.r]), y = d3.scaleLinear().domain([0, mx * 1.08]).range([H - P.b, P.t]);
      const ln = S => d3.line().x((_, i) => x(i)).y(d => y(d.v)).curve(d3.curveMonotoneX)(S);
      const area = d3.area().x((_, i) => x(i)).y0(H - P.b).y1(d => y(d.v)).curve(d3.curveMonotoneX)(A);
      const ticks = d3.range(0, n, Math.max(1, Math.ceil(n / 7)));
      const lab = i => (A[i] || B[i]).k.slice(gran === 'day' ? 5 : 0);
      const strips = d3.range(n).map(i => {
        const a = A[i], b = B && B[i];
        const tt = [a ? `A ${a.k}${a.part ? '*' : ''}: ${fmtV(a.v)}${a.est ? ' ≈' : ''}` : '', b ? `B ${b.k}${b.part ? '*' : ''}: ${fmtV(b.v)}${b.est ? ' ≈' : ''}` : ''].filter(Boolean).join('\n');
        return `<rect x="${x(i) - (W - P.l - P.r) / n / 2}" y="${P.t}" width="${Math.max(1, (W - P.l - P.r) / n)}" height="${H - P.b - P.t}" fill="transparent"><title>${tt}</title></rect>`;
      }).join('');
      const leg = `<g transform="translate(${P.l},14)"><rect width="12" height="3" y="-2" fill="${CA}"/><text x="18" y="2" fill="#e6d5b0" font-size="11">${lblA()}</text></g>` +
        (B ? `<g transform="translate(${P.l},30)"><rect width="12" height="3" y="-2" fill="${CB}"/><text x="18" y="2" fill="#e6d5b0" font-size="11">${lblB()}</text></g>` : '');
      return `<svg id="cChart" viewBox="0 0 ${W} ${H}" style="width:100%;background:rgba(255,255,255,.02);border-radius:10px" font-family="Be Vietnam Pro, Arial, sans-serif">
        ${leg}
        ${y.ticks(4).map(v => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(230,213,176,.08)"/><text x="${P.l - 6}" y="${y(v) + 4}" fill="#e6d5b0" font-size="10" text-anchor="end">${fmtV(v)}</text>`).join('')}
        <path d="${area}" fill="rgba(240,138,52,.16)"/>
        <path d="${ln(A)}" fill="none" stroke="${CA}" stroke-width="2"/>
        ${B ? `<path d="${ln(B)}" fill="none" stroke="${CB}" stroke-width="2" stroke-dasharray="5 3"/>` : ''}
        ${n <= 40 ? A.map((d, i) => `<circle cx="${x(i)}" cy="${y(d.v)}" r="2.6" fill="${CA}"/>`).join('') + (B ? B.map((d, i) => `<circle cx="${x(i)}" cy="${y(d.v)}" r="2.6" fill="${CB}"/>`).join('') : '') : ''}
        ${ticks.map(i => `<text x="${x(i)}" y="${H - 10}" fill="#e6d5b0" font-size="10" text-anchor="middle">${lab(i)}</text>`).join('')}
        ${strips}
      </svg>`;
    }
    function calDay(S, mx, title, col) {      // GitHub-style calendar: columns = weeks, rows = Mon…Sun
      if (!S.length) return '';
      const c = 12, g = 2, first = new Date(S[0].k + 'T00:00:00Z'), off = (first.getUTCDay() + 6) % 7;
      const weeks = Math.ceil((S.length + off) / 7), W = 34 + weeks * (c + g) + 6, H = 30 + 7 * (c + g) + 4;
      const wd = (lang === 'vi' ? ['T2', '', 'T4', '', 'T6', '', 'CN'] : ['Mo', '', 'We', '', 'Fr', '', 'Su']);
      let cells = '', months = '', lastM = '';
      S.forEach((d, i) => {
        const j = i + off, cx = 34 + Math.floor(j / 7) * (c + g), cy = 30 + (j % 7) * (c + g), t = d.v > 0 ? Math.pow(d.v / mx, .55) : 0;
        cells += `<rect x="${cx}" y="${cy}" width="${c}" height="${c}" rx="2" fill="${d.v > 0 ? ramp(t) : 'rgba(230,213,176,.07)'}"><title>${d.k}: ${fmtV(d.v)}${d.est ? ' ≈' : ''}</title></rect>`;
        const m = d.k.slice(0, 7); if (m !== lastM) { lastM = m; months += `<text x="${cx}" y="24" fill="#e6d5b0" font-size="10">${L().mS(+m.slice(5) - 1)}${m.slice(5) === '01' || !months ? ' ' + m.slice(0, 4) : ''}</text>`; }
      });
      return `<div style="overflow-x:auto"><svg class="cCal" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="Be Vietnam Pro, Arial, sans-serif">
        <text x="0" y="11" fill="${col}" font-size="11" font-weight="600">${title}</text>${months}
        ${wd.map((w, k) => `<text x="0" y="${30 + k * (c + g) + 10}" fill="rgba(230,213,176,.6)" font-size="9">${w}</text>`).join('')}${cells}</svg></div>`;
    }
    function calMonth(S, mx, title, col) {     // rows = years, columns = 12 months
      if (!S.length) return '';
      const ys = [...new Set(S.map(d => +d.k.slice(0, 4)))], c = 40, h = 22, g = 3, W = 46 + 12 * (c + g), H = 34 + ys.length * (h + g);
      const by = new Map(S.map(d => [d.k, d]));
      let s = `<text x="0" y="11" fill="${col}" font-size="11" font-weight="600">${title}</text>` +
        d3.range(12).map(i => `<text x="${46 + i * (c + g) + c / 2}" y="28" fill="rgba(230,213,176,.6)" font-size="10" text-anchor="middle">${L().mS(i)}</text>`).join('');
      ys.forEach((y, r) => {
        const yy = 34 + r * (h + g);
        s += `<text x="0" y="${yy + 15}" fill="rgba(230,213,176,.6)" font-size="10">${y}</text>`;
        for (let m = 1; m <= 12; m++) {
          const d = by.get(`${y}-${p2(m)}`); if (!d) continue;
          const t = d.v > 0 ? Math.pow(d.v / mx, .55) : 0, x0 = 46 + (m - 1) * (c + g);
          s += `<rect x="${x0}" y="${yy}" width="${c}" height="${h}" rx="3" fill="${d.v > 0 ? ramp(t) : 'rgba(230,213,176,.07)'}"><title>${d.k}${d.part ? '*' : ''}: ${fmtV(d.v)}${d.est ? ' ≈' : ''}</title></rect>` +
            `<text x="${x0 + c / 2}" y="${yy + 15}" fill="${t > .55 ? '#fff' : '#09112c'}" font-size="9" text-anchor="middle" pointer-events="none">${d.v >= 1000 ? (d.v / 1000).toFixed(1) + 'k' : Math.round(d.v)}${d.part ? '*' : ''}</text>`;
        }
      });
      return `<div style="overflow-x:auto"><svg class="cCal" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="Be Vietnam Pro, Arial, sans-serif">${s}</svg></div>`;
    }
    function cards(A, B, gran) {
      const sum = S => d3.sum(S, d => d.v), pk = S => S.reduce((a, d) => d.v > a.v ? d : a, S[0] || { k: '–', v: 0 });
      const sA = sum(A), pA = pk(A), avg = S => S.length ? sum(S) / S.length : 0;
      let h = `<div class="kcard" style="border-color:${CA}55"><span>A · ${tx('total')}</span><b>${fmtV(sA)}</b><span>${tx(gran === 'day' ? 'avgD' : 'avgM')}: ${fmtC(avg(A))}</span></div>
               <div class="kcard"><span>A · ${tx(gran === 'day' ? 'peakD' : 'peakM')}</span><b>${pA.k}</b><span>${fmtV(pA.v)} ${L().unit}</span></div>`;
      if (B) {
        const sB = sum(B), pB = pk(B), d = sB > 0 ? (sA / sB - 1) * 100 : NaN;
        h += `<div class="kcard" style="border-color:${CB}55"><span>B · ${tx('total')}</span><b>${fmtV(sB)}</b><span>${tx(gran === 'day' ? 'peakD' : 'peakM')}: ${pB.k} (${fmtV(pB.v)})</span></div>
              <div class="kcard"><span>${tx('diff')}</span><b style="color:${isNaN(d) ? '#fff3da' : d >= 0 ? '#ff8a65' : '#81c784'}">${isNaN(d) ? '–' : (d >= 0 ? '+' : '') + d.toFixed(0) + '%'}</b><span>${isNaN(d) ? '' : 'A ' + tx(d >= 0 ? 'higher' : 'lower')}</span></div>`;
      }
      return `<div class="cards3">${h}</div>`;
    }

    /* ---------- Download ---------- */
    const dl = (blob, name) => { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); };
    function svgPng(svg, name) {
      if (!svg) return;
      const vb = svg.viewBox.baseVal, w = vb && vb.width ? vb.width : svg.clientWidth, h = vb && vb.height ? vb.height : svg.clientHeight;
      const cl = svg.cloneNode(true); cl.setAttribute('xmlns', 'http://www.w3.org/2000/svg'); cl.setAttribute('width', w); cl.setAttribute('height', h); cl.removeAttribute('style');
      const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect'); bg.setAttribute('width', w); bg.setAttribute('height', h); bg.setAttribute('fill', '#0a1433'); cl.insertBefore(bg, cl.firstChild);
      const img = new Image(), url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(cl)], { type: 'image/svg+xml' }));
      img.onload = () => { const cv = document.createElement('canvas'); cv.width = w * 2; cv.height = h * 2; const c = cv.getContext('2d'); c.scale(2, 2); c.drawImage(img, 0, 0); URL.revokeObjectURL(url); cv.toBlob(b => dl(b, name), 'image/png'); };
      img.src = url;
    }

    /* ---------- Tab render ---------- */
    const provOpts = selV => `<option value="-1"${selV === -1 ? ' selected' : ''}>${tx('nat')}</option>` +
      provs.map((f, i) => [f.properties.shapeName, i]).sort((a, b) => a[0].localeCompare(b[0], 'vi'))
        .map(([n, i]) => `<option value="${i}"${i === selV ? ' selected' : ''}>${n}</option>`).join('');
    const dateIn = (id, v) => `<input id="${id}" type="date" class="rinp mono" min="${minD()}" max="${maxD()}" value="${v}">`;
    function renderCmp() {
      initState();
      const body = q('#anaBody');
      body.innerHTML = `
        <div class="lab" style="color:${CA}">${tx('a')}</div>
        <div class="rform">
          <div><div class="lab">${tx('prov')}</div><select id="cAp" class="rinp">${provOpts(C.a.p)}</select></div>
          <div><div class="lab">${tx('from')}</div>${dateIn('cAf', C.a.f)}</div>
          <div><div class="lab">${tx('to')}</div>${dateIn('cAt', C.a.t)}</div>
        </div>
        <div><div class="lab" style="margin-bottom:6px">${tx('cmpWith')}</div>
          <div class="seg" id="cMode" style="max-width:100%;overflow-x:auto">
            <button data-cm="none">${tx('none')}</button><button data-cm="time">${tx('time')}</button><button data-cm="prov">${tx('other')}</button></div></div>
        <div id="cBbox" style="display:${C.mode === 'none' ? 'none' : 'block'}">
          <div class="lab" style="color:${CB};margin-bottom:6px">${tx('b')}</div>
          <div class="rform">
            <div><div class="lab">${tx('prov')}</div><select id="cBp" class="rinp"${C.mode === 'time' ? ' disabled' : ''}>${provOpts(C.b.p)}</select></div>
            <div><div class="lab">${tx('from')}</div>${dateIn('cBf', C.b.f)}</div>
            <div><div class="lab">${tx('to')}</div>${dateIn('cBt', C.b.t)}</div>
          </div>
        </div>
        <div id="cOut" style="display:flex;flex-direction:column;gap:14px"></div>`;
      qa('#cMode button').forEach(b => b.classList.toggle('act', b.dataset.cm === C.mode));
      q('#cMode').onclick = e => {
        const m = e.target.closest('button')?.dataset.cm; if (!m || m === C.mode) return;
        C.mode = m; C.bTouched = false;
        if (m === 'time') C.b = { p: C.a.p, f: shiftYear(C.a.f, -1), t: shiftYear(C.a.t, -1) };
        if (m === 'prov') { const alt = C.a.p === -1 ? 0 : -1; C.b = { p: C.b.p === C.a.p ? alt : C.b.p, f: C.a.f, t: C.a.t }; }
        renderCmp();
      };
      const read = () => {
        const fix = (f, t) => { f = clampD(f || minD()); t = clampD(t || maxD()); return f <= t ? [f, t] : [t, f]; };
        [C.a.f, C.a.t] = fix(q('#cAf').value, q('#cAt').value); C.a.p = +q('#cAp').value;
        if (C.mode !== 'none') { [C.b.f, C.b.t] = fix(q('#cBf').value, q('#cBt').value); C.b.p = C.mode === 'time' ? C.a.p : +q('#cBp').value; }
      };
      // Until the user edits B themselves, B follows A: "same province" = A's period shifted back 1 year, "other province" = same period as A
      const syncB = () => {
        if (C.mode === 'none' || C.bTouched) return;
        if (C.mode === 'time') { C.b.f = shiftYear(C.a.f, -1); C.b.t = shiftYear(C.a.t, -1); } else { C.b.f = C.a.f; C.b.t = C.a.t; }
        if (q('#cBf')) { q('#cBf').value = C.b.f; q('#cBt').value = C.b.t; }
      };
      ['#cAp', '#cAf', '#cAt', '#cBp', '#cBf', '#cBt'].forEach(s => {
        const el = q(s); if (!el) return;
        el.onchange = () => {
          if (s.startsWith('#cB')) C.bTouched = true;
          read(); syncB();
          if (C.mode === 'time' && q('#cBp')) q('#cBp').value = C.a.p;
          run();
        };
      });
      run();
    }
    let tok = 0;
    async function run() {
      const my = ++tok, out = q('#cOut'); if (!out) return;
      out.innerHTML = `<div style="color:var(--dim);font-size:13px">${tx('loading')}</div>`;
      const hasB = C.mode !== 'none';
      const gran = Math.max(spanDays(C.a.f, C.a.t), hasB ? spanDays(C.b.f, C.b.t) : 0) <= 366 ? 'day' : 'month';
      const get = r => gran === 'day' ? daily(r.p, r.f, r.t) : Promise.resolve(monthly(r.p, r.f, r.t));
      const [A, B] = await Promise.all([get(C.a), hasB ? get(C.b) : null]);
      if (my !== tok || !q('#cOut')) return;
      if (!A.length) { out.innerHTML = `<div style="color:var(--dim)">${tx('empty')}</div>`; return; }
      const mx = Math.max(1, d3.max(A, d => d.v), B ? d3.max(B, d => d.v) || 0 : 0);
      const cal = gran === 'day' ? calDay : calMonth;
      out.innerHTML = `${cards(A, B, gran)}
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
          <div class="lab">${tx('chart')} · ${tx(gran === 'day' ? 'byDay' : 'byMonth')}</div>
          <div style="display:flex;gap:6px;flex-wrap:wrap"><button class="pill" id="cCsv">${tx('csv')}</button><button class="pill" id="cPng">${tx('png')}</button><button class="pill" id="cPngCal">${tx('pngCal')}</button></div>
        </div>
        ${lineChart(A, B, gran)}
        <div class="lab">${tx('cal')} · ${tx(gran === 'day' ? 'byDay' : 'byMonth')}</div>
        ${cal(A, mx, lblA(), CA)}${B ? cal(B, mx, lblB(), CB) : ''}
        <div style="font-size:12px;color:var(--dim);line-height:1.55">${tx(gran === 'day' ? 'noteDay' : 'noteMonth')}${B ? ' ' + tx('alignNote') : ''}</div>`;
      const base = `fire_${C.a.p < 0 ? 'VN' : provs[C.a.p].properties.id}_${C.a.f}_${C.a.t}` + (B ? `_vs_${C.b.p < 0 ? 'VN' : provs[C.b.p].properties.id}_${C.b.f}_${C.b.t}` : '');
      q('#cCsv').onclick = () => {
        const n = Math.max(A.length, B ? B.length : 0), rows = ['idx,A_date,A_value,A_estimate' + (B ? ',B_date,B_value,B_estimate' : '')];
        for (let i = 0; i < n; i++) {
          const a = A[i], b = B && B[i];
          rows.push([i + 1, a ? a.k : '', a ? a.v.toFixed(1) : '', a ? (a.est ? 1 : 0) : ''].concat(B ? [b ? b.k : '', b ? b.v.toFixed(1) : '', b ? (b.est ? 1 : 0) : ''] : []).join(','));
        }
        dl(new Blob(['﻿' + `# A: ${lblA()}` + (B ? `\n# B: ${lblB()}` : '') + `\n# ${gran}\n` + rows.join('\n')], { type: 'text/csv' }), base + '.csv');
      };
      q('#cPng').onclick = () => svgPng(q('#cChart'), base + '_chart.png');
      q('#cPngCal').onclick = () => qa('#cOut .cCal').forEach((s, i) => svgPng(s, base + (i ? '_calendar_B.png' : '_calendar_A.png')));
    }

    /* ---------- Hook into renderAnalytics ---------- */
    const orig = renderAnalytics;
    renderAnalytics = function () {
      const ps = q('#anaProv');
      if (anaTab !== 'cmp') { if (ps) ps.style.display = ''; return orig(); }
      if (ps) ps.style.display = 'none';            // this tab has its own province picker
      qa('#anaTabs button').forEach(b => b.classList.toggle('act', b.dataset.tab === 'cmp'));
      renderCmp();
    };

    console.info('[compare] module on');
  } catch (err) {
    console.error('[compare] error, module disabled', err);
  }
})();
