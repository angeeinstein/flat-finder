/* flat-finder map view */

(function () {
  'use strict';

  // ---- Map init ----
  const map = L.map('map').setView([48.21, 16.37], 11);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);

  const aptLayer = L.markerClusterGroup({
    showCoverageOnHover: false,
    maxClusterRadius: 45,
    spiderfyOnMaxZoom: true,
    chunkedLoading: true,
  }).addTo(map);
  const targetLayer = L.layerGroup().addTo(map);

  // In-memory data store — loaded once, filtered client-side
  let allApartments = [];
  let allTargets = [];

  // ---- Color helpers ----
  function colorForScore(s) {
    if (s == null) return '#6c757d';
    if (s >= 80) return '#198754';
    if (s >= 60) return '#0d6efd';
    if (s >= 40) return '#ffc107';
    return '#dc3545';
  }
  function colorForPrice(p) {
    if (p == null) return '#6c757d';
    if (p < 700)  return '#198754';
    if (p < 1000) return '#0d6efd';
    if (p < 1400) return '#ffc107';
    return '#dc3545';
  }
  function colorForTravel(min) {
    if (min == null) return '#6c757d';
    if (min < 15) return '#198754';
    if (min < 30) return '#0d6efd';
    if (min < 45) return '#ffc107';
    return '#dc3545';
  }
  function colorForStatus(s) {
    const m = {
      favorite: '#198754', accepted: '#198754',
      interesting: '#0d6efd', applied: '#0d6efd',
      viewed: '#17a2b8', contacted: '#17a2b8', viewing_scheduled: '#17a2b8',
      rejected: '#dc3545',
      archived: '#adb5bd',
    };
    return m[s] || '#6c757d';
  }

  // ---- HTML helpers ----
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function travelBadge(min, km) {
    if (min == null) return '';
    const color = colorForTravel(min);
    const distStr = km != null ? ` · ${km.toFixed(1)} km` : '';
    return `<div class="map-popup-travel" style="color:${color}">` +
           `<i class="bi bi-clock"></i> <strong>${Math.round(min)} min</strong>${distStr}</div>`;
  }

  function popupHtml(apt) {
    const parts = [];
    if (apt.thumbnail_url) {
      parts.push(`<img class="map-popup-thumb" src="${esc(apt.thumbnail_url)}" alt="">`);
    }
    parts.push(`<div class="map-popup-title">${esc(apt.title || `Apartment #${apt.id}`)}</div>`);
    if (apt.address) {
      parts.push(`<div class="map-popup-address">${esc(apt.address)}</div>`);
    }

    // Price / area row
    const priceVal = apt.total || apt.price;
    const priceStr = priceVal != null ? `<strong>€${Math.round(priceVal)}</strong>/mo` : null;
    const areaStr  = apt.area  != null ? `${Math.round(apt.area)} m²` : null;
    const m2Str    = apt.cost_per_m2 != null ? `€${apt.cost_per_m2.toFixed(1)}/m²` : null;
    const roomStr  = apt.rooms != null ? `${apt.rooms} rm` : null;
    const metrics  = [priceStr, areaStr, m2Str, roomStr].filter(Boolean);
    if (metrics.length) {
      parts.push(`<div class="map-popup-metrics">${metrics.join('<span class="mx-1 text-muted">·</span>')}</div>`);
    }

    // Travel time (if target selected)
    parts.push(travelBadge(apt.travel_time_min, apt.travel_distance_km));

    // Score + offline badge
    const extras = [];
    if (apt.score != null) extras.push(`Score <strong>${apt.score}</strong>`);
    if (apt.is_offline) extras.push(`<span style="color:#dc3545">⚠ Offline</span>`);
    if (extras.length) parts.push(`<div class="map-popup-extras">${extras.join(' · ')}</div>`);

    parts.push(`<a href="${esc(apt.detail_url)}" class="map-popup-btn">Open listing →</a>`);
    return parts.join('');
  }

  // ---- Filter state ----
  function getFilters() {
    const travelVal = parseInt(document.getElementById('f-max-travel').value, 10);
    return {
      maxPrice:  parseFloat(document.getElementById('f-max-price').value)  || null,
      minRooms:  parseFloat(document.getElementById('f-min-rooms').value)  || null,
      minArea:   parseFloat(document.getElementById('f-min-area').value)   || null,
      maxTravel: travelVal > 0 ? travelVal : null,
      balcony:   document.getElementById('f-balcony').checked,
      parking:   document.getElementById('f-parking').checked,
      onlineOnly: document.getElementById('f-online').checked,
    };
  }

  function passesFilter(apt, f) {
    const price = apt.total ?? apt.price;
    if (f.maxPrice  != null && (price == null || price > f.maxPrice))      return false;
    if (f.minRooms  != null && (apt.rooms == null || apt.rooms < f.minRooms)) return false;
    if (f.minArea   != null && (apt.area  == null || apt.area  < f.minArea))  return false;
    if (f.maxTravel != null && (apt.travel_time_min == null || apt.travel_time_min > f.maxTravel)) return false;
    if (f.balcony  && !apt.has_balcony && !apt.has_terrace && !apt.has_garden) return false;
    if (f.parking  && !apt.has_parking)  return false;
    if (f.onlineOnly && apt.is_offline)  return false;
    return true;
  }

  function activeFilterCount(f) {
    let n = 0;
    if (f.maxPrice  != null) n++;
    if (f.minRooms  != null) n++;
    if (f.minArea   != null) n++;
    if (f.maxTravel != null) n++;
    if (f.balcony)   n++;
    if (f.parking)   n++;
    if (f.onlineOnly) n++;
    return n;
  }

  // ---- Render markers from in-memory store ----
  function renderMarkers() {
    const colorBy = document.getElementById('color-by').value;
    const filters = getFilters();

    aptLayer.clearLayers();
    let shown = 0;
    const total = allApartments.length;

    allApartments.forEach(apt => {
      if (!passesFilter(apt, filters)) return;
      shown++;

      let color;
      if      (colorBy === 'price')       color = colorForPrice(apt.total ?? apt.price);
      else if (colorBy === 'status')      color = colorForStatus(apt.status);
      else if (colorBy === 'travel_time') color = colorForTravel(apt.travel_time_min);
      else                                color = colorForScore(apt.score);

      const marker = L.circleMarker([apt.lat, apt.lng], {
        radius: 9, color, weight: 2, fillColor: color, fillOpacity: 0.75,
      });
      marker.bindPopup(popupHtml(apt), { maxWidth: 240, className: 'map-popup' });
      aptLayer.addLayer(marker);
    });

    // Update badge and count
    const countEl = document.getElementById('filter-count');
    if (countEl) {
      countEl.textContent = shown < total
        ? `Showing ${shown} of ${total} listings`
        : `${total} listing${total !== 1 ? 's' : ''}`;
    }
    const badge = document.getElementById('filter-badge');
    if (badge) {
      const n = activeFilterCount(filters);
      badge.textContent = n;
      badge.classList.toggle('d-none', n === 0);
    }
  }

  function renderTargets() {
    targetLayer.clearLayers();
    allTargets.forEach(t => {
      const icon = L.divIcon({
        className: '',
        html: `<div class="map-target-icon"><i class="bi bi-flag-fill"></i></div>`,
        iconSize: [32, 32],
        iconAnchor: [16, 16],
      });
      const m = L.marker([t.lat, t.lng], { icon, zIndexOffset: 1000 });
      m.bindPopup(
        `<strong>${esc(t.name)}</strong>${t.address ? `<br><small>${esc(t.address)}</small>` : ''}`,
        { maxWidth: 200 }
      );
      targetLayer.addLayer(m);
    });
  }

  // ---- Load from API (fired when target/mode changes) ----
  async function load() {
    const targetId = document.getElementById('target').value;
    const mode     = document.getElementById('mode').value;
    const params   = new URLSearchParams({ mode });
    if (targetId) params.set('target_id', targetId);

    let data;
    try {
      data = await flatFinder.api('/api/map/markers?' + params.toString());
    } catch (e) {
      return;
    }

    allApartments = data.apartments;
    allTargets    = data.targets;

    // Show/hide travel-time slider depending on whether a target is selected
    const travelWrap = document.getElementById('travel-wrap');
    if (targetId) {
      travelWrap.style.display = '';
    } else {
      travelWrap.style.display = 'none';
      document.getElementById('f-max-travel').value = 0;
      document.getElementById('travel-output').textContent = 'any';
    }

    renderTargets();
    renderMarkers();

    // Fit bounds to all visible data
    const pts = [
      ...allApartments.map(a => [a.lat, a.lng]),
      ...allTargets.filter(t => t.lat != null).map(t => [t.lat, t.lng]),
    ];
    if (pts.length) map.fitBounds(pts, { padding: [40, 40] });
  }

  // ---- Wire up controls ----

  // Target / mode changes → reload from server (travel times change)
  ['target', 'mode'].forEach(id =>
    document.getElementById(id).addEventListener('change', load)
  );

  // Color-by → re-render in memory (no server round-trip)
  document.getElementById('color-by').addEventListener('change', renderMarkers);

  // Filter inputs → re-render in memory
  ['f-max-price', 'f-min-rooms', 'f-min-area'].forEach(id =>
    document.getElementById(id).addEventListener('input', renderMarkers)
  );
  ['f-balcony', 'f-parking', 'f-online'].forEach(id =>
    document.getElementById(id).addEventListener('change', renderMarkers)
  );

  const travelSlider = document.getElementById('f-max-travel');
  const travelOutput = document.getElementById('travel-output');
  travelSlider.addEventListener('input', () => {
    const v = parseInt(travelSlider.value, 10);
    travelOutput.textContent = v > 0 ? `≤ ${v} min` : 'any';
    renderMarkers();
  });

  document.getElementById('reset-filters').addEventListener('click', () => {
    document.getElementById('f-max-price').value = '';
    document.getElementById('f-min-rooms').value = '';
    document.getElementById('f-min-area').value  = '';
    document.getElementById('f-max-travel').value = 0;
    document.getElementById('travel-output').textContent = 'any';
    document.getElementById('f-balcony').checked  = false;
    document.getElementById('f-parking').checked  = false;
    document.getElementById('f-online').checked   = false;
    renderMarkers();
  });

  // Sidebar toggle
  const sidebar = document.getElementById('map-sidebar');
  document.getElementById('filter-toggle').addEventListener('click', () => {
    sidebar.classList.toggle('collapsed');
    setTimeout(() => map.invalidateSize(), 220);
  });

  load();
})();
