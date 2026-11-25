// Read-only runtime geometry audit for live browsers (preview_evaluate / Playwright).
// Zero dependencies, no DOM mutations; returns a compact JSON summary.
(() => {
  const MAX = 15;
  const vw = window.innerWidth || document.documentElement.clientWidth || 0;
  const vh = window.innerHeight || document.documentElement.clientHeight || 0;
  const px = (v) => parseFloat(v) || 0;
  const rnd = (v) => Math.round(v * 10) / 10;
  const tag = (el) => {
    const cls = typeof el.className === 'string' ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 3).join('.') : '';
    return `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}${cls ? `.${cls}` : ''}`;
  };
  const anims = typeof document.getAnimations === 'function' ? document.getAnimations().filter((a) => a.playState === 'running') : [];
  const geomRe = /^(?:transform|translate|rotate|scale|width|height|minWidth|maxWidth|minHeight|maxHeight|blockSize|inlineSize|gridTemplateRows|gridTemplateColumns|flexBasis|gap|rowGap|columnGap|padding.*|margin.*|top|left|right|bottom)$/;
  const moving = (el) => anims.some((a) => {
    const t = a.effect && a.effect.target;
    return t && (t === el || (typeof t.contains === 'function' && t.contains(el))) &&
      typeof a.effect.getKeyframes === 'function' && a.effect.getKeyframes().some((k) => Object.keys(k).some((p) => geomRe.test(p)));
  });
  const unhidden = (el) => {
    for (let a = el; a; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) < 0.05) return false;
    }
    return true;
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width >= 1 && r.height >= 1 && r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw && unhidden(el);
  };
  const inFlow = (el, stop) => {
    for (let a = el; a && a !== stop; a = a.parentElement) {
      const pos = getComputedStyle(a).position;
      if (pos === 'absolute' || pos === 'fixed') return false;
    }
    return true;
  };
  const textRects = (el) => {
    const rects = [];
    if (typeof document.createTreeWalker !== 'function' || typeof document.createRange !== 'function') return rects;
    const w = document.createTreeWalker(el, 4);
    for (let n; (n = w.nextNode());) {
      if (!n.textContent || !n.textContent.trim() || !n.parentElement || n.parentElement.closest('.sr-only, [aria-hidden="true"]') || !visible(n.parentElement) || !inFlow(n.parentElement, el)) continue;
      const rg = document.createRange();
      rg.selectNodeContents(n);
      for (const b of rg.getClientRects()) if (b.width >= 0.5 && b.height >= 0.5) rects.push(b);
    }
    return rects;
  };
  const all = [document.body || document.documentElement, ...document.querySelectorAll('*')].filter(Boolean);
  const horizontalOverflow = [], controlIssues = [], containerBottomClip = [], brokenImages = [], smallText = [], wrappedUnits = [];
  const docScroll = document.documentElement ? document.documentElement.scrollWidth : 0;
  if (docScroll > vw + 1) {
    for (const el of all) {
      if (el === document.documentElement || el === document.body || !visible(el)) continue;
      let scroller = false;
      for (let a = el.parentElement; a; a = a.parentElement) if (['auto', 'scroll'].includes(getComputedStyle(a).overflowX)) { scroller = true; break; }
      if (scroller) continue;
      const r = el.getBoundingClientRect();
      if (r.right > vw + 1 || r.left < -1) {
        horizontalOverflow.push({ element: tag(el), left: rnd(r.left), right: rnd(r.right), viewportWidth: vw });
        if (horizontalOverflow.length >= MAX) break;
      }
    }
    if (!horizontalOverflow.length) horizontalOverflow.push({ element: 'html', scrollWidth: rnd(docScroll), viewportWidth: vw });
  }
  const checked = { controls: 0, containers: 0, images: 0 };
  const ctrlSel = 'button, [role="button"], input[type="submit"], input[type="button"], [data-ui-control]';
  for (const el of document.querySelectorAll(ctrlSel)) {
    if (!visible(el) || moving(el)) continue;
    const cs = getComputedStyle(el);
    if (cs.writingMode && cs.writingMode !== 'horizontal-tb') continue;
    checked.controls++;
    const r = el.getBoundingClientRect();
    const bl = px(cs.borderLeftWidth), br = px(cs.borderRightWidth), bt = px(cs.borderTopWidth), bb = px(cs.borderBottomWidth);
    const atoms = textRects(el);
    for (const ch of el.querySelectorAll('svg, img')) {
      if (!visible(ch) || !inFlow(ch, el)) continue;
      atoms.push(ch.getBoundingClientRect());
      if (ch.tagName.toLowerCase() === 'svg' && ['flex', 'inline-flex'].includes(cs.display)) {
        const cr = ch.getBoundingClientRect(), ccs = getComputedStyle(ch);
        const aw = px(ch.getAttribute && ch.getAttribute('width')) || px(ccs.width);
        const ah = px(ch.getAttribute && ch.getAttribute('height')) || px(ccs.height);
        if (((aw >= 8 && cr.width < aw * 0.75) || (ah >= 8 && cr.height < ah * 0.75)) && controlIssues.length < MAX) {
          controlIssues.push({ rule: 'squeezed-icon', element: tag(el), width: rnd(cr.width), expected: rnd(aw) });
        }
      }
    }
    const clipX = ['hidden', 'clip'].includes(cs.overflowX) && el.scrollWidth > el.clientWidth + 2;
    const clipY = ['hidden', 'clip'].includes(cs.overflowY) && el.scrollHeight > el.clientHeight + 2;
    if (controlIssues.length < MAX && (clipX || clipY)) {
      controlIssues.push({ rule: 'control-overflow', element: tag(el), width: rnd(r.width), scrollWidth: rnd(el.scrollWidth) });
    } else if (atoms.length && controlIssues.length < MAX) {
      const minL = Math.min(...atoms.map((a) => a.left)), maxR = Math.max(...atoms.map((a) => a.right));
      const minT = Math.min(...atoms.map((a) => a.top)), maxB = Math.max(...atoms.map((a) => a.bottom));
      if (minL < r.left + bl - 1.5 || maxR > r.right - br + 1.5 || minT < r.top + bt - 1.5 || maxB > r.bottom - bb + 1.5) {
        controlIssues.push({ rule: 'control-overflow', element: tag(el), width: rnd(r.width), scrollWidth: rnd(el.scrollWidth) });
      } else {
        const pL = px(cs.paddingLeft), pR = px(cs.paddingRight), lGap = minL - (r.left + bl), rGap = (r.right - br) - maxR;
        if ((pL <= 1 && pR >= 6 && lGap <= 2 && rGap >= 5) || (pR <= 1 && pL >= 6 && rGap <= 2 && lGap >= 5)) {
          controlIssues.push({ rule: 'control-edge-inset', element: tag(el), leftGap: rnd(lGap), rightGap: rnd(rGap) });
        }
      }
    }
  }
  for (const el of all) {
    if (el.matches(ctrlSel) || !el.children.length || !visible(el) || el.matches('html, body') || el.closest('[data-crop]')) continue;
    const cs = getComputedStyle(el), padB = px(cs.paddingBottom);
    if (padB < 8 || cs.display === 'inline' || ['auto', 'scroll'].includes(cs.overflowY)) continue;
    const kids = [...el.children].filter((c) => visible(c) && inFlow(c, el));
    if (!kids.length || moving(el)) continue;
    const last = kids.reduce((a, b) => (a.getBoundingClientRect().bottom > b.getBoundingClientRect().bottom ? a : b));
    if (moving(last)) continue;
    let edge = el.getBoundingClientRect().bottom - px(cs.borderBottomWidth), bound = el;
    for (let a = el.parentElement; a; a = a.parentElement) {
      if (a.matches('html, body') || a.hasAttribute('data-crop')) break;
      const ac = getComputedStyle(a);
      if (['auto', 'scroll'].includes(ac.overflowY)) break;
      if (['hidden', 'clip'].includes(ac.overflowY)) {
        const lower = a.getBoundingClientRect().bottom - px(ac.borderBottomWidth);
        if (lower < edge) { edge = lower; bound = a; }
      }
    }
    checked.containers++;
    const avail = edge - last.getBoundingClientRect().bottom;
    if (avail < padB - 2 && containerBottomClip.length < MAX) {
      containerBottomClip.push({ rule: 'container-block-inset', element: tag(el), availableBottom: rnd(avail), paddingBottom: rnd(padB), boundary: tag(bound) });
    }
  }
  for (const img of document.querySelectorAll('img')) {
    if (!unhidden(img)) continue;
    checked.images++;
    if (img.complete && img.naturalWidth === 0 && brokenImages.length < MAX) {
      brokenImages.push({ element: tag(img), src: (img.getAttribute('src') || '').slice(0, 100) });
    }
  }
  const seenSmall = new Set();
  for (const el of all) {
    if (el.matches('html, body, script, style, sub, sup') || el.closest('.sr-only, [aria-hidden="true"]') || !visible(el)) continue;
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (r.width <= 2 || r.height <= 2 || cs.clip === 'rect(0px, 0px, 0px, 0px)') continue;
    const hasDirectText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent && n.textContent.trim());
    if (hasDirectText && px(cs.fontSize) < 11 && !seenSmall.has(el) && smallText.length < MAX) {
      seenSmall.add(el);
      smallText.push({ element: tag(el), fontSize: rnd(px(cs.fontSize)), text: el.textContent.trim().slice(0, 40) });
    }
  }
  for (const el of document.querySelectorAll('.price, .stat-value, .metric-value, [data-metric], [data-price]')) {
    if (!visible(el)) continue;
    const txt = (el.textContent || '').trim();
    if (!txt || txt.length > 32 || !/\d/.test(txt)) continue;
    const rects = textRects(el);
    if (rects.length > 1) {
      const tops = rects.map((b) => b.top);
      if (Math.max(...tops) - Math.min(...tops) > 4 && wrappedUnits.length < MAX) {
        wrappedUnits.push({ element: tag(el), text: txt, lines: rects.length });
      }
    }
  }
  const counts = {
    horizontalOverflow: horizontalOverflow.length, controlIssues: controlIssues.length,
    containerBottomClip: containerBottomClip.length, brokenImages: brokenImages.length,
    smallText: smallText.length, wrappedUnits: wrappedUnits.length,
  };
  counts.total = Object.values(counts).reduce((a, b) => a + b, 0);
  const status = (checked.controls + checked.containers + checked.images === 0) ? 'inconclusive' : counts.total > 0 ? 'issues' : 'ok';
  return {
    viewport: { width: vw, height: vh }, checked, counts, status,
    horizontalOverflow, controlIssues, containerBottomClip, brokenImages, smallText, wrappedUnits,
    note: 'Geometry check only; inspect visual hierarchy, contrast, and interaction states on screenshots.',
  };
})();
