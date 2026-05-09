/* flat-finder map view */

(function () {
  const map = L.map('map').setView([48.21, 16.37], 11);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap', maxZoom: 19,
  }).addTo(map);

  let aptLayer = L.layerGroup().addTo(map);
  let targetLayer = L.layerGroup().addTo(map);

  function colorForScore(s) {
    if (s == null) return '#6c757d';
    if (s >= 80) return '#198754';
    if (s >= 60) return '#0d6efd';
    if (s >= 40) return '#ffc107';
    return '#dc3545';
  }
  function colorForPrice(p) {
    if (p == null) return '#6c757d';
    if (p < 700) return '#198754';
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
    const m = {favorite:'#198754',accepted:'#198754',interesting:'#0d6efd',
               viewed:'#17a2b8',contacted:'#17a2b8',applied:'#0d6efd',
               rejected:'#dc3545',archived:'#adb5bd'};
    return m[s] || '#6c757d';
  }

  function popupHtml(apt) {
    let lines = [];
    if (apt.thumbnail_url) lines.push(`<img class="map-popup-thumb" src="${apt.thumbnail_url}">`);
    lines.push(`<strong>${escapeHtml(apt.title || ('Apartment #' + apt.id))}</strong>`);
    if (apt.address) lines.push(`<div class="small text-muted">${escapeHtml(apt.address)}</div>`);
    let info = [];
    if (apt.total != null) info.push(`€${apt.total.toFixed(0)}`);
    if (apt.area != null) info.push(`${apt.area.toFixed(0)} m²`);
    if (apt.rooms != null) info.push(`${apt.rooms} rooms`);
    if (apt.score != null) info.push(`<span class="badge bg-primary">${apt.score}</span>`);
    if (info.length) lines.push(`<div>${info.join(' · ')}</div>`);
    if (apt.travel_time_min != null) {
      lines.push(`<div class="small">Travel: ${apt.travel_time_min.toFixed(0)} min · ${apt.travel_distance_km.toFixed(1)} km</div>`);
    }
    lines.push(`<a href="${apt.detail_url}" class="btn btn-sm btn-primary mt-2">Open</a>`);
    return lines.join('');
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  async function load() {
    const colorBy = document.getElementById('color-by').value;
    const targetId = document.getElementById('target').value;
    const mode = document.getElementById('mode').value;
    const params = new URLSearchParams({color_by: colorBy, mode});
    if (targetId) params.set('target_id', targetId);
    let data;
    try { data = await flatFinder.api('/api/map/markers?' + params.toString()); }
    catch (e) { return; }

    aptLayer.clearLayers();
    targetLayer.clearLayers();

    const bounds = [];
    data.apartments.forEach(apt => {
      let color;
      if (colorBy === 'price') color = colorForPrice(apt.total || apt.price);
      else if (colorBy === 'status') color = colorForStatus(apt.status);
      else if (colorBy === 'travel_time') color = colorForTravel(apt.travel_time_min);
      else color = colorForScore(apt.score);

      const m = L.circleMarker([apt.lat, apt.lng], {
        radius: 9, color, weight: 2, fillColor: color, fillOpacity: 0.7,
      });
      m.bindPopup(popupHtml(apt));
      aptLayer.addLayer(m);
      bounds.push([apt.lat, apt.lng]);
    });

    data.targets.forEach(t => {
      const m = L.marker([t.lat, t.lng], {
        icon: L.divIcon({className: '', html: `<div style="background:#ff5722;color:#fff;border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;border:2px solid white;box-shadow:0 0 4px rgba(0,0,0,.4)"><i class="bi bi-flag-fill"></i></div>`, iconSize: [30,30]})
      });
      m.bindPopup(`<strong>${escapeHtml(t.name)}</strong><br><small>${escapeHtml(t.address || '')}</small>`);
      targetLayer.addLayer(m);
      bounds.push([t.lat, t.lng]);
    });

    if (bounds.length) map.fitBounds(bounds, { padding: [40, 40] });
  }

  ['color-by','target','mode'].forEach(id => {
    document.getElementById(id).addEventListener('change', load);
  });
  load();
})();
