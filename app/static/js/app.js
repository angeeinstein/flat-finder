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
