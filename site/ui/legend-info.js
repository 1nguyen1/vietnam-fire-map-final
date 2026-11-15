/* =====================================================================
   ui/legend-info.js  —  ⓘ button explaining the "Fire intensity" legend
   Team 268LTK · NASA Space Apps 2026
   AI use: Written with assistance from Claude (Anthropic); reviewed and tested by team 268LTK.

   Adds a small ⓘ button next to the legend title. Tapping it shows a short
   explanation that updates with the current view:
     - Fire map: what one 1 km cell's color means, during [the period being viewed],
       darkest color = from N points up (N changes with Day / Month / Quarter / Year).
     - Patrol map: meaning of the 3 priority colors.
     - Patrol map: also mentions the land-cover filter if ui/landcover.js is on.
   index.html's original code is NOT changed.

   Remove the module: delete the line containing "ui/legend-info.js" in index.html.
   ===================================================================== */
(function () {
  'use strict';
  try {
    const leg = document.querySelector('#legend'), title = document.querySelector('#legTitle');
    if (!leg || !title || typeof periodText !== 'function' || typeof scaleMax !== 'function') {
      console.warn('[legend-info] legend not found, module disabled');
      return;
    }

    /* ---------- Styles ---------- */
    const st = document.createElement('style');
    st.textContent =
      '#legHead{display:flex;align-items:center;gap:6px}' +
      '#legInfo{width:18px;height:18px;flex:0 0 18px;border-radius:50%;border:1px solid rgba(230,213,176,.45);color:#fff3da;' +
      'font-size:11px;line-height:16px;text-align:center;padding:0;cursor:pointer;background:rgba(230,213,176,.08);font-family:inherit}' +
      '#legInfo:hover,#legInfo.on{background:#f08a34;border-color:#f08a34;color:#1b0e04}' +
      '#legPop{position:absolute;z-index:9;width:min(290px,calc(100vw - 24px));padding:12px 14px;border-radius:12px;' +
      'border:1px solid rgba(230,213,176,.28);background:rgba(9,17,44,.97);color:#fff3da;font-size:12.5px;line-height:1.5;' +
      'box-shadow:0 12px 30px rgba(0,0,0,.4);opacity:0;visibility:hidden;transform:translateY(4px);transition:opacity .15s,transform .15s,visibility 0s .15s}' +
      '#legPop.open{opacity:1;visibility:visible;transform:none;transition:opacity .15s,transform .15s}' +
      '#legPop h4{margin:0 22px 6px 0;font-size:13px;font-weight:600}' +
      '#legPop p{margin:0 0 6px}#legPop p.d{color:var(--dim);font-size:11.5px;margin:6px 0 0}' +
      '#legPop ul{margin:4px 0 0;padding:0;list-style:none}#legPop li{margin:0 0 5px;display:flex;gap:7px;align-items:flex-start}' +
      '#legPop li i{flex:0 0 10px;width:10px;height:10px;border-radius:3px;margin-top:4px}' +
      '#legPop .bar{height:8px;border-radius:4px;margin:6px 0 2px;background:linear-gradient(90deg,rgba(230,213,176,.14),#f2c063 28%,#f08a34 52%,#e2482a 76%,#a80f1d)}' +
      '#legPop .ends{display:flex;justify-content:space-between;font-size:11px;color:var(--dim)}' +
      '#legPop .x{position:absolute;top:6px;right:8px;border:0;background:none;color:var(--dim);font-size:15px;cursor:pointer;padding:2px 4px}';
    document.head.appendChild(st);

    /* ---------- Button next to the title ---------- */
    const head = document.createElement('div');
    head.id = 'legHead';
    title.parentNode.insertBefore(head, title);
    head.appendChild(title);
    const btn = document.createElement('button');
    btn.id = 'legInfo'; btn.type = 'button'; btn.textContent = 'i';
    head.appendChild(btn);

    const pop = document.createElement('div');
    pop.id = 'legPop'; pop.setAttribute('role', 'dialog');
    document.body.appendChild(pop);

    /* ---------- Content ---------- */
    const vi = () => lang === 'vi';
    const lower = s => s.charAt(0).toLowerCase() + s.slice(1);
    function html() {
      const V = vi();
      const lc = window.LC268 && LC268.current() !== 'all' ? LC268.name(LC268.current()) : '';
      const lcP = lc ? `<p class="d">${V ? 'Đang lọc lớp phủ đất' : 'Land-cover filter'}: <b style="color:#c5e1a5">${lc}</b>.</p>` : '';
      if (patrolMode) {
        return V
          ? `<h4>Bản đồ ưu tiên tuần tra</h4>
             <p>Mỗi ô 1 km là một nơi từng cháy trong tháng đã chọn, giai đoạn 2012–2025. Màu cho biết mức ưu tiên tuần tra:</p>
             <ul><li><i style="background:#e22b2b"></i><span><b>Cao</b>: cháy lặp lại từ 7/14 năm trở lên <b>và</b> khó tiếp cận</span></li>
             <li><i style="background:#f08a34"></i><span><b>Trung bình</b>: cháy lặp lại từ 4/14 năm trở lên</span></li>
             <li><i style="background:#f2c063"></i><span><b>Thấp</b>: cháy 1–3/14 năm</span></li></ul>
             <p class="d">Bấm vào một ô để xem khoảng cách tới đường xe, độ dốc và chỉ đường.</p>${lcP}`
          : `<h4>Patrol priority map</h4>
             <p>Each 1 km cell is a place that burned in the selected month, 2012–2025. The color is the patrol priority:</p>
             <ul><li><i style="background:#e22b2b"></i><span><b>High</b>: burned in 7+ of 14 years <b>and</b> hard to reach</span></li>
             <li><i style="background:#f08a34"></i><span><b>Medium</b>: burned in 4+ of 14 years</span></li>
             <li><i style="background:#f2c063"></i><span><b>Low</b>: burned in 1–3 of 14 years</span></li></ul>
             <p class="d">Tap a cell to see the distance to a vehicle road, slope and directions.</p>${lcP}`;
      }
      const mx = fmtC(scaleMax()), per = periodText();
      return V
        ? `<h4>Mức độ cháy</h4>
           <p>Mỗi ô 1 km được tô màu theo <b>số điểm cháy nằm trong ô đó</b>, tính cho ${lower(per)}.</p>
           <div class="bar"></div><div class="ends"><span>0 · ít</span><span>${mx}+ · nhiều</span></div>
           <p style="margin-top:6px;margin-bottom:0">Màu đỏ đậm nhất = <b>từ ${mx} điểm cháy trở lên</b> trong một ô. Mốc này đổi theo chế độ Ngày / Tháng / Quý / Năm.</p>`
        : `<h4>Fire intensity</h4>
           <p>Each 1 km cell is colored by the <b>number of fire points inside it</b>, for ${per}.</p>
           <div class="bar"></div><div class="ends"><span>0 · few</span><span>${mx}+ · many</span></div>
           <p style="margin-top:6px;margin-bottom:0">Darkest red = <b>${mx} or more fire points</b> in one cell. This threshold changes with Day / Month / Quarter / Year.</p>`;
    }

    /* ---------- Open / close / position ---------- */
    function place() {
      const r = leg.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
      if (innerWidth >= 900 && r.right + 12 + w < innerWidth) {          // computer: to the right of the legend
        pop.style.left = (r.right + 10) + 'px';
        pop.style.top = Math.max(8, Math.min(r.top, innerHeight - h - 8)) + 'px';
      } else {                                                            // phone: below the legend
        pop.style.left = Math.max(12, Math.min(r.left, innerWidth - w - 12)) + 'px';
        pop.style.top = Math.min(r.bottom + 8, innerHeight - h - 8) + 'px';
      }
    }
    const isOpen = () => pop.classList.contains('open');
    function open() {
      pop.innerHTML = html() + `<button class="x" type="button" aria-label="${vi() ? 'Đóng' : 'Close'}">✕</button>`;
      pop.querySelector('.x').onclick = close;
      place(); pop.classList.add('open'); btn.classList.add('on');
    }
    function close() { pop.classList.remove('open'); btn.classList.remove('on'); }
    const label = () => btn.setAttribute('aria-label', vi() ? 'Giải thích thang màu' : 'Explain the color scale');
    label();

    btn.addEventListener('click', e => { e.stopPropagation(); isOpen() ? close() : open(); label(); });
    pop.addEventListener('click', e => e.stopPropagation());
    document.addEventListener('click', () => { if (isOpen()) close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    addEventListener('resize', close);
    document.querySelector('#map')?.addEventListener('pointerdown', close);

    console.info('[legend-info] module on');
  } catch (err) {
    console.error('[legend-info] error, module disabled', err);
  }
})();
