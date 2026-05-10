/* flat-finder global JS helpers */

window.flatFinder = window.flatFinder || {};

flatFinder.csrfToken = function() {
  const m = document.querySelector('meta[name="csrf-token"]');
  return m ? m.getAttribute('content') : null;
};

flatFinder.api = async function(url, options = {}) {
  const opts = Object.assign({
    method: 'GET',
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    credentials: 'same-origin',
  }, options);
  const csrf = flatFinder.csrfToken();
  if (csrf) opts.headers['X-CSRFToken'] = csrf;
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`;
    try { const j = await resp.json(); if (j.error) msg = j.error; } catch (_) {}
    throw new Error(msg);
  }
  if (resp.status === 204) return null;
  return resp.json();
};

/* ---------- Address autocomplete ----------
 * Attaches to any <input data-address-autocomplete> on page load.
 * Optional: data-lat-target / data-lng-target are CSS selectors for
 * fields that should receive lat/lng when the user picks a suggestion.
 */
flatFinder.attachAddressAutocomplete = function(input) {
  if (!input || input._ffAutocompleteAttached) return;
  input._ffAutocompleteAttached = true;

  const wrapper = document.createElement('div');
  wrapper.className = 'ff-autocomplete-wrapper';
  input.parentNode.insertBefore(wrapper, input);
  wrapper.appendChild(input);

  const list = document.createElement('div');
  list.className = 'ff-autocomplete-list';
  list.style.display = 'none';
  wrapper.appendChild(list);

  let pending = null;
  let activeIndex = -1;

  const close = () => { list.style.display = 'none'; activeIndex = -1; };
  const render = (results) => {
    list.innerHTML = '';
    if (!results.length) { close(); return; }
    results.forEach((r, i) => {
      const item = document.createElement('div');
      item.className = 'ff-autocomplete-item';
      item.textContent = r.display;
      item.addEventListener('mousedown', (ev) => {
        ev.preventDefault();
        input.value = r.display;
        const latSel = input.dataset.latTarget;
        const lngSel = input.dataset.lngTarget;
        if (latSel) document.querySelector(latSel)?.setAttribute('value', r.lat);
        if (lngSel) document.querySelector(lngSel)?.setAttribute('value', r.lng);
        if (latSel) { const el = document.querySelector(latSel); if (el) el.value = r.lat; }
        if (lngSel) { const el = document.querySelector(lngSel); if (el) el.value = r.lng; }
        close();
      });
      list.appendChild(item);
    });
    list.style.display = 'block';
  };

  const search = async () => {
    const q = input.value.trim();
    if (q.length < 3) { close(); return; }
    if (pending) clearTimeout(pending);
    pending = setTimeout(async () => {
      try {
        const data = await flatFinder.api('/api/geocode/search?q=' + encodeURIComponent(q));
        render(data.results || []);
      } catch (_) { close(); }
    }, 350);
  };

  input.addEventListener('input', search);
  input.addEventListener('focus', search);
  input.addEventListener('blur', () => setTimeout(close, 150));
  input.addEventListener('keydown', (ev) => {
    const items = list.querySelectorAll('.ff-autocomplete-item');
    if (!items.length) return;
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      activeIndex = (activeIndex + 1) % items.length;
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      activeIndex = (activeIndex - 1 + items.length) % items.length;
    } else if (ev.key === 'Enter' && activeIndex >= 0) {
      ev.preventDefault();
      items[activeIndex].dispatchEvent(new MouseEvent('mousedown'));
      return;
    } else if (ev.key === 'Escape') {
      close();
      return;
    } else { return; }
    items.forEach((el, i) => el.classList.toggle('active', i === activeIndex));
  });
};

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('input[data-address-autocomplete]')
    .forEach(flatFinder.attachAddressAutocomplete);
});

/* ---------- Lightbox gallery ----------
 * Looks for `[data-lightbox-group="X"]` elements; clicking opens an overlay
 * that lets the user step through every image in the same group.
 */
flatFinder.lightbox = (function() {
  let overlay, imgEl, counterEl, items = [], index = 0;

  function build() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.className = 'ff-lightbox';
    overlay.innerHTML = `
      <button class="ff-lightbox-btn ff-lightbox-close" aria-label="Close">&times;</button>
      <button class="ff-lightbox-btn ff-lightbox-prev" aria-label="Previous">&lsaquo;</button>
      <img alt="">
      <button class="ff-lightbox-btn ff-lightbox-next" aria-label="Next">&rsaquo;</button>
      <div class="ff-lightbox-counter"></div>
    `;
    document.body.appendChild(overlay);
    imgEl = overlay.querySelector('img');
    counterEl = overlay.querySelector('.ff-lightbox-counter');
    overlay.querySelector('.ff-lightbox-close').addEventListener('click', close);
    overlay.querySelector('.ff-lightbox-prev').addEventListener('click', (e) => { e.stopPropagation(); step(-1); });
    overlay.querySelector('.ff-lightbox-next').addEventListener('click', (e) => { e.stopPropagation(); step(1); });
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', (e) => {
      if (!overlay.classList.contains('open')) return;
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft') step(-1);
      else if (e.key === 'ArrowRight') step(1);
    });
  }

  function show() {
    if (!items.length) return;
    const it = items[index];
    imgEl.src = it.full || it.src;
    imgEl.alt = it.alt || '';
    counterEl.textContent = (index + 1) + ' / ' + items.length;
  }
  function step(dir) {
    if (!items.length) return;
    index = (index + dir + items.length) % items.length;
    show();
  }
  function open(group, startIndex) {
    build();
    items = group;
    index = Math.max(0, Math.min(startIndex || 0, group.length - 1));
    show();
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
  function close() {
    if (!overlay) return;
    overlay.classList.remove('open');
    document.body.style.overflow = '';
  }
  return { open, close };
})();

document.addEventListener('DOMContentLoaded', () => {
  // Group nodes by their data-lightbox-group attribute. Each item should also
  // carry data-lightbox-full (full-size URL) and (optionally) an inner <img>.
  const groups = {};
  document.querySelectorAll('[data-lightbox-group]').forEach((el) => {
    const g = el.dataset.lightboxGroup;
    (groups[g] = groups[g] || []).push(el);
  });
  Object.entries(groups).forEach(([name, els]) => {
    const items = els.map((el) => {
      const inner = el.querySelector('img');
      return {
        full: el.dataset.lightboxFull || (inner ? inner.src : ''),
        src: inner ? inner.src : '',
        alt: el.dataset.lightboxAlt || (inner ? inner.alt : ''),
      };
    });
    els.forEach((el, i) => {
      el.addEventListener('click', (ev) => {
        ev.preventDefault();
        flatFinder.lightbox.open(items, i);
      });
    });
  });
});

flatFinder.showToast = function(message, type = 'info') {
  const container = document.getElementById('toastContainer') || (() => {
    const c = document.createElement('div');
    c.id = 'toastContainer';
    c.className = 'toast-container position-fixed top-0 end-0 p-3';
    c.style.zIndex = 1090;
    document.body.appendChild(c);
    return c;
  })();
  const t = document.createElement('div');
  t.className = `toast align-items-center text-bg-${type} border-0 show`;
  t.innerHTML = `<div class="d-flex"><div class="toast-body">${message}</div>
    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
  container.appendChild(t);
  setTimeout(() => t.remove(), 5000);
};
