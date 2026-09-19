const state = {
  zone: null,       // leaflet layer
  route: null,      // leaflet layer
  traceLayer: null,
  cutLayer: null,
  fixtures: null,
  current: null,
  playing: false,
  timer: null,
};

const map = L.map("map").setView([22.3416, 73.1512], 16);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

async function fetchJson(url, body) {
  const res = await fetch(url, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

async function loadTraceData(name) {
  return fetchJson("/api/trace/" + encodeURIComponent(name));
}

async function loadZoneData(name) {
  return fetchJson("/api/zone/" + encodeURIComponent(name));
}

function initUi() {
  const traceSel = document.getElementById("trace");
  const zoneSel = document.getElementById("zone");
  const routeSel = document.getElementById("route");

  fetchJson("/api/fixtures").then((fx) => {
    state.fixtures = fx;
    fx.traces.forEach((t) => {
      const o = document.createElement("option");
      o.value = t;
      o.textContent = t;
      traceSel.appendChild(o);
    });
    fx.zones.forEach((z) => {
      const o = document.createElement("option");
      o.value = z;
      o.textContent = z;
      zoneSel.appendChild(o);
    });
    fx.routes.forEach((r) => {
      const o = document.createElement("option");
      o.value = r;
      o.textContent = r;
      routeSel.appendChild(o);
    });
    // kick off with the illegal cut
    audit();
  });
}

async function audit() {
  stopPlayback();
  const trace = document.getElementById("trace").value;
  const zones = [document.getElementById("zone").value];
  const route = document.getElementById("route").value;

  // draw geometry from source data
  clearLayers();
  const zoneData = await loadZoneData(zones[0]);
  const zoneRing = zoneData.ring.map((p) => [p.lat, p.lon]);
  state.zone = L.polygon(zoneRing, { color: "#e11d48", weight: 2, fillOpacity: 0.15 }).addTo(map);
  zoneRing.forEach((ring) => map.addLayer(L.circleMarker(ring, { color: "#e11d48", radius: 4 })));

  if (route) {
    const routeData = await loadTraceData(route);
    const pts = routeData.points.map((p) => [p.lat, p.lon]);
    state.route = L.polyline(pts, { color: "#16a34a", weight: 3, opacity: 0.85 }).addTo(map);
  }

  const res = await fetchJson("/api/audit", { trace, zones, route });
  state.current = res;

  const tracePts = res.points.map((p) => [p.lat, p.lon]);
  state.traceLayer = L.polyline(tracePts, {
    color: VERDICT_COLOR(res.verdict),
    weight: 3,
    opacity: 0.9,
  }).addTo(map);
  res.points.forEach((p, i) => {
    map.addLayer(
      L.circleMarker([p.lat, p.lon], {
        color: VERDICT_COLOR(res.verdict),
        radius: 3,
        fillColor: VERDICT_COLOR(res.verdict),
        fillOpacity: 1,
      })
    );
  });

  if (res.seg_start >= 0 && res.seg_end >= 0) {
    const cut = res.points.slice(res.seg_start, res.seg_end + 1).map((p) => [p.lat, p.lon]);
    state.cutLayer = L.polyline(cut, { color: "#e11d48", weight: 6, opacity: 0.95 }).addTo(map);
  }

  const bounds = L.latLngBounds(tracePts);
  if (state.route) for (const p of state.route.getLatLngs()) bounds.extend(p);
  if (state.zone) for (const p of state.zone.getLatLngs()[0]) bounds.extend(p);
  map.fitBounds(bounds.pad(0.1));

  renderVerdict(res);
}

function clearLayers() {
  [state.zone, state.route, state.traceLayer, state.cutLayer].forEach((l) => l && map.removeLayer(l));
  state.zone = state.route = state.traceLayer = state.cutLayer = null;
}

function renderVerdict(res) {
  const verdict = document.getElementById("verdict");
  verdict.className = "badge " + (res.verdict === "CLEAN" ? "clean" : res.verdict === "VIOLATION" ? "violation" : "ambiguous");
  verdict.textContent = res.verdict;
  document.getElementById("reason").textContent = res.reason;
  document.getElementById("state").textContent = res.state;
  document.getElementById("severity").textContent = res.severity;

  const metrics = document.getElementById("metrics");
  metrics.innerHTML = "";
  if (res.metrics && "trace_len_m" in res.metrics) {
    const m = res.metrics;
    metrics.appendChild(field("trace distance", m.trace_len_m + " m"));
    metrics.appendChild(field("legal route distance", m.route_len_m + " m"));
    metrics.appendChild(field("shortcut factor", "x" + m.shortcut_factor));
    metrics.appendChild(field("wrong-way bearing", m.bearing_delta_deg + " deg"));
  } else if (res.metrics && res.metrics.anchor_problems) {
    metrics.appendChild(field("anchor check", res.metrics.anchor_problems.join("; ")));
  } else {
    metrics.appendChild(field("no metrics", "n/a"));
  }

  const review = document.getElementById("review-outcome");
  review.textContent = "";
  document.getElementById("review-btn").disabled = res.state !== "PENDING_REVIEW";
}

function field(label, value) {
  const d = document.createElement("div");
  d.className = "metric";
  const l = document.createElement("span");
  l.textContent = label;
  const v = document.createElement("strong");
  v.textContent = value;
  d.append(l, v);
  return d;
}

async function review() {
  const btn = document.getElementById("review-btn");
  btn.disabled = true;
  btn.textContent = "Asking Tier-3 agent...";
  const out = document.getElementById("review-outcome");

  const body = {
    trace: document.getElementById("trace").value,
    zones: [document.getElementById("zone").value],
    route: document.getElementById("route").value,
  };
  try {
    const res = await fetchJson("/api/review", body);
    out.textContent = res.agent_recommendation
      ? `Tier-3 agent → ${res.agent_recommendation}`
      : res.agent_text || "agent had nothing to say";
    if (res.agent_error) out.textContent += ` (${res.agent_error})`;
  } catch (e) {
    out.textContent = "agent unreachable: " + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Ask Tier-3 agent";
  }
}

function stopPlayback() {
  state.playing = false;
  clearInterval(state.timer);
  state.timer = null;
}

function VERDICT_COLOR(v) {
  if (v === "CLEAN") return "#16a34a";
  if (v === "VIOLATION") return "#e11d48";
  return "#d97706";
}

async function play() {
  if (!state.current) return;
  if (state.traceLayer) map.removeLayer(state.traceLayer);

  const pts = state.current.points;
  let i = 0;
  const marker = L.marker([pts[0].lat, pts[0].lon]).addTo(map);
  // show the cut overlap as it animates if one exists
  const chunk = L.polyline([], { color: VERDICT_COLOR(state.current.verdict), weight: 3, opacity: 0.9 }).addTo(map);

  state.timer = setInterval(() => {
    i = Math.min(i + 1, pts.length - 1);
    chunk.setLatLngs(pts.slice(0, i + 1).map((p) => [p.lat, p.lon]));
    marker.setLatLng([pts[i].lat, pts[i].lon]);
    if (i >= pts.length - 1) {
      clearInterval(state.timer);
      state.timer = null;
      map.removeLayer(marker);
    }
  }, 400);
}

window.addEventListener("DOMContentLoaded", initUi);
window.audit = audit;
window.review = review;
window.play = play;