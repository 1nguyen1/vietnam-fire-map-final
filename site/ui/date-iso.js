/* date-iso.js — 268LTK
 * Shows every <input type="date"> as ISO 8601 (YYYY-MM-DD), whatever the
 * browser language is. The native date picker and the input's value are
 * untouched (the value is always YYYY-MM-DD), so compare.js keeps working.
 * Remove the <script src="ui/date-iso.js"> line in index.html to undo.
 * Written with assistance from Claude (Anthropic); reviewed and tested by team 268LTK.
 */
(function () {
  'use strict';
  try {
    const css = document.createElement('style');
    css.id = 'dIsoCss';
    css.textContent = `
      .dIso{position:relative;display:block}
      .dIso>input.dIsoIn{color:transparent!important;cursor:pointer}
      .dIso>input.dIsoIn::-webkit-datetime-edit{opacity:0}
      .dIso>.dIsoTxt{position:absolute;top:0;bottom:0;display:flex;align-items:center;
        pointer-events:none;white-space:nowrap;color:#fff3da}
      .dIso>.dIsoTxt.ph{opacity:.45}
      .dIso>input.dIsoIn:disabled+.dIsoTxt{opacity:.45}
      .dIso>input.dIsoIn:focus-visible{outline:2px solid rgba(255,176,77,.7);outline-offset:1px}`;
    document.head.appendChild(css);

    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');

    function render(el) {
      const t = el._dIsoTxt; if (!t) return;
      const v = desc.get.call(el);
      t.textContent = v || 'YYYY-MM-DD';
      t.classList.toggle('ph', !v);
    }

    function wrap(el) {
      if (el.dataset.iso) return;
      el.dataset.iso = '1';
      const box = document.createElement('span');
      box.className = 'dIso';
      el.parentNode.insertBefore(box, el);
      box.appendChild(el);
      el.classList.add('dIsoIn');
      const t = document.createElement('span');
      t.className = 'dIsoTxt';
      const cs = getComputedStyle(el);
      t.style.left = (parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth)) + 'px';
      t.style.fontFamily = cs.fontFamily;
      t.style.fontSize = cs.fontSize;
      t.style.letterSpacing = cs.letterSpacing;
      box.appendChild(t);
      el._dIsoTxt = t;
      el.title = 'YYYY-MM-DD';
      // compare.js also sets .value from code (region B follows A): catch that too
      Object.defineProperty(el, 'value', {
        configurable: true,
        get() { return desc.get.call(this); },
        set(v) { desc.set.call(this, v); render(this); }
      });
      el.addEventListener('input', () => render(el));
      el.addEventListener('change', () => render(el));
      // the text is hidden, so a click anywhere opens the calendar
      el.addEventListener('click', () => {
        if (el.disabled || typeof el.showPicker !== 'function') return;
        try { el.showPicker(); } catch (e) { /* not allowed here: native behaviour */ }
      });
      render(el);
    }

    const scan = root => (root.querySelectorAll ? root.querySelectorAll('input[type="date"]:not([data-iso])') : []).forEach(wrap);
    scan(document);
    new MutationObserver(ms => {
      for (const m of ms) for (const n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        if (n.matches && n.matches('input[type="date"]')) wrap(n); else scan(n);
      }
    }).observe(document.body, { childList: true, subtree: true });
  } catch (err) {
    console.error('[date-iso] error, module disabled', err);
  }
})();
