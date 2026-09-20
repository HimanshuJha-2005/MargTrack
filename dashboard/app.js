const JUNCTION = [22.3228, 73.2550];

const state = {
  fixtures: null,
  current: null,
  playing: false,
  timer: null,
};

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      basemap: {
        type: "raster",
        tiles: ["/tiles/{z}/{x}/{y}.png"],
        tileSize: 256,
        maxzoom: 19,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
      },
    },
    layers: [{ id: "basemap", type: "raster", source: "basemap" }],
  },
  center: JUNCTION,
  zoom: 16,
  maxZoom: 19,
});

function emptyGeojson() {
  return { type: "FeatureCollection", features: [] };
}

function geojsonSource() {
  return { type: "geojson", data: emptyGeojson() };
}

function lineFeatures(coords) {
  return [{ type: "Feature", geometry: { type: "LineString", coordinates: coords } }];
}

const OVERLAY_SOURCES = ["route", "zone", "lanes", "trace", "cut"];

function ensureOverlay() {
  if (!map.isStyleLoaded()) return false;
  OVERLAY_SOURCES.forEach((name) => {
    if (!map.getSource(name)) map.addSource(name, geojsonSource());
  });
  if (!map.getLayer("route-layer")) {
    map.addLayer({ id: "route-layer", type: "line", source: "route", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#16a34a", "line-width": 3.5, "line-opacity": 0.9 } });
  }
  if (!map.getLayer("zone-fill")) {
    map.addLayer({ id: "zone-fill", type: "fill", source: "zone", paint: { "fill-color": "#e11d48", "fill-opacity": 0.18 } });
    map.addLayer({ id: "zone-line", type: "line", source: "zone", paint: { "line-color": "#e11d48", "line-width": 1.5, "line-dasharray": [2, 1.5], "line-opacity": 0.85 } });
  }
  if (!map.getLayer("lane-layer")) {
    map.addLayer({ id: "lane-layer", type: "line", source: "lanes", layout: { "line-cap": "round" }, paint: { "line-color": "#0ea5e9", "line-width": 2, "line-dasharray": [1, 2.5], "line-opacity": 0.9 } });
  }
  if (!map.getLayer("trace-line")) {
    map.addLayer({ id: "trace-line", type: "line", source: "trace", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#d97706", "line-width": 3, "line-opacity": 0.9 } });
  }
  if (!map.getLayer("cut-line")) {
    map.addLayer({ id: "cut-line", type: "line", source: "cut", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#e11d48", "line-width": 6, "line-opacity": 0.95 } });
  }
  return true;
}

function setSource(name, features) {
  if (map.getSource(name)) {
    map.getSource(name).setData({ type: "FeatureCollection", features });
  }
}

function clearGeo() {
  OVERLAY_SOURCES.forEach((name) => {
    if (map.getSource(name)) map.getSource(name).setData(emptyGeojson());
  });
}

async function fetchJson(url, body) {
  const res = await fetch(url, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

function ready() {
  return new Promise((resolve) => {
    if (map.isStyleLoaded()) return resolve();
    map.on("load", () => resolve());
    setTimeout(resolve, 8000);
  });
}

function initUi() {
  const traceSel = document.getElementById("trace");
  fetchJson("/api/fixtures").then((fx) => {
    state.fixtures = fx;
    fx.traces.forEach((t) => {
      const o = document.createElement("option");
      o.value = t;
      o.textContent = fx.trace_labels[t] || t;
      traceSel.appendChild(o);
    });
    showHint();
    ready().then(audit);
  });
}

function showHint() {
  const t = document.getElementById("trace").value;
  const fx = state.fixtures;
  document.getElementById("trace-hint").textContent = fx && fx.trace_labels[t] ? fx.trace_labels[t] : "";
}

async function audit() {
  stopPlayback();
  const trace = document.getElementById("trace").value;
  const zones = state.fixtures.zones;
  const route = state.fixtures.trace_routes[trace] || state.fixtures.routes[0];

  clearGeo();
  await ready();
  ensureOverlay();

  const [zoneData, routeData, laneNames] = await Promise.all([
    fetchJson("/api/zone/" + zones[0]),
    fetchJson("/api/route/" + route),
    Promise.resolve(state.fixtures.lanes),
  ]);

  setSource("zone", [{ type: "Feature", geometry: { type: "Polygon", coordinates: [zoneData.ring.map((p) => [p.lon, p.lat])] } }]);
  setSource("route", lineFeatures(routeData.points.map((p) => [p.lon, p.lat])));

  const laneFeats = [];
  for (const ln of laneNames) {
    const d = await fetchJson("/api/lane/" + ln);
    laneFeats.push(...lineFeatures(d.points.map((p) => [p.lon, p.lat])));
  }
  setSource("lanes", laneFeats);

  const res = await fetchJson("/api/audit", { trace, zones, route, lanes: laneNames });
  state.current = res;

  const coords = res.points.map((p) => [p.lon, p.lat]);
  setSource("trace", lineFeatures(coords));
  if (res.cut && res.cut.length) setSource("cut", lineFeatures(res.cut.map((p) => [p.lon, p.lat])));

  fitJunction(coords);
  renderVerdict(res);
}

function fitJunction(coords) {
  if (!coords.length) return map.jumpTo({ center: JUNCTION, zoom: 16 });
  const bounds = new maplibregl.LngLatBounds();
  coords.forEach((c) => bounds.extend(c));
  map.fitBounds(bounds, { padding: 60, maxZoom: 17 });
}

function renderVerdict(res) {
  const verdict = document.getElementById("verdict");
  verdict.className = "badge " + (res.verdict === "CLEAN" ? "clean" : res.verdict === "VIOLATION" ? "violation" : "ambiguous");
  verdict.textContent = res.verdict;
  document.getElementById("reason").textContent = res.human_reason || res.reason;
  document.getElementById("state").textContent = res.state;
  document.getElementById("severity").textContent = res.severity;

  const vtype = document.getElementById("vtype");
  if (res.violation_type && res.violation_type !== "") {
    vtype.textContent = res.violation_type.replace("ViolationType.", "");
    vtype.hidden = false;
  } else {
    vtype.hidden = true;
    vtype.textContent = "";
  }

  renderOpsMetrics(res.ops_metrics || []);
  renderEngineLog(res.metrics || {}, res);

  // safety ledger + Cedar gate
  const s = res.safety || {};
  document.getElementById("score-value").textContent = s.safety_score ?? "—";
  const scoreSub = document.getElementById("score-sub");
  scoreSub.textContent = penaltyText(s) || (s.status || "").toLowerCase();
  const chip = document.getElementById("cedar-chip");
  const d = res.dispatch || {};
  chip.textContent = d.decision === "ALLOWED" ? "ALLOWED" : "DENIED";
  chip.className = "cedar-chip " + (d.decision === "ALLOWED" ? "allow" : "deny");
  document.getElementById("cedar-note").textContent = d.decision === "ALLOWED"
    ? "dispatches open"
    : "dispatches blocked";
  document.getElementById("trip-status").className = "trip-status " + ((res.trip_status || s.status || "").toLowerCase().replace(" ", "-"));
  document.getElementById("trip-status").textContent = res.trip_status || s.status || "—";

  const replay = document.getElementById("play-btn");
  replay.disabled = !res.points || !res.points.length;

  const btn = document.getElementById("review-btn");
  btn.disabled = res.state !== "PENDING_REVIEW";
  document.getElementById("review-block").hidden = true;
  document.getElementById("review-outcome").textContent = "";
}

function penaltyText(s) {
  const p = s.penalty;
  if (p == null) return "";
  if (p > 0) return "+" + p + " recovered";
  if (p < 0) return p + " demerits";
  return "";
}

function renderOpsMetrics(rows) {
  const box = document.getElementById("ops-metrics");
  box.innerHTML = "";
  rows.forEach((r) => box.appendChild(field(r.label, r.value)));
}

function renderEngineLog(m, res) {
  const box = document.getElementById("metrics");
  box.innerHTML = "";
  if ("trace_len_m" in m) {
    box.appendChild(field("trace distance", m.trace_len_m + " m"));
    box.appendChild(field("legal distance", m.route_len_m + " m"));
    box.appendChild(field("shortcut factor", "x" + m.shortcut_factor));
    if (m.bearing_delta_deg != null) box.appendChild(field("heading delta", m.bearing_delta_deg + " °"));
  } else if ("bearing_delta_deg" in m) {
    if (m.lane) box.appendChild(field("against lane", m.lane));
    box.appendChild(field("heading delta", m.bearing_delta_deg + " °"));
  } else if ("off_route_frac" in m) {
    box.appendChild(field("points off route", m.off_route_count + " / " + m.total_points));
    box.appendChild(field("off-route share", Math.round(m.off_route_frac * 100) + " %"));
  } else {
    box.appendChild(field("points", m.total_points ?? res.points?.length ?? "—"));
    if (m.on_corridor) box.appendChild(field("on corridor", m.on_corridor));
    box.appendChild(field("off-route tolerance", m.off_route_tolerance + " m"));
  }
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
  btn.textContent = "Asking Tier-3 agent…";
  const out = document.getElementById("review-outcome");
  out.className = "review-outcome";
  const block = document.getElementById("review-block");
  block.hidden = true;

  const body = {
    trace: document.getElementById("trace").value,
    zones: state.fixtures.zones,
    route: state.fixtures.trace_routes[document.getElementById("trace").value] || state.fixtures.routes[0],
    lanes: state.fixtures.lanes,
  };
  try {
    const res = await fetchJson("/api/review", body);
    const verdict = res.agent_recommendation || "—";
    if (verdict !== "SKIPPED") {
      block.hidden = false;
      const reco = document.getElementById("review-reco");
      reco.textContent = verdict === "VIOLATION" ? "CONFIRM VIOLATION" : verdict === "NOISE" ? "DISMISS AS NOISE" : "REVIEW";
      reco.className = "review-reco " + (verdict === "VIOLATION" ? "danger" : verdict === "NOISE" ? "warn" : "info");
      const detail = res.agent_text || res.engine_reason || "";
      document.getElementById("review-evidence").textContent = detail ? detail.slice(0, 220) : "—";
    } else {
      out.textContent = "Tier-3 agent → " + res.engine_reason;
    }
  } catch (e) {
    out.className = "review-outcome info";
    out.textContent = "agent unreachable: " + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Ask the Tier-3 review agent";
  }
}

async function onUpload(file) {
  stopPlayback();
  const text = await file.text();
  let pts;
  try {
    pts = parseTraceJson(text);
  } catch (e) {
    alert("Invalid trace JSON: " + e.message);
    return;
  }
  if (!pts.length) { alert("Trace has no points."); return; }

  await ready();
  ensureOverlay();
  clearGeo();

  const zones = state.fixtures.zones;
  const body = { points: pts, zones, lanes: state.fixtures.lanes };
  try {
    const res = await fetchJson("/api/audit", body);
    state.current = res;
    const coords = res.points.map((p) => [p.lon, p.lat]);
    setSource("trace", lineFeatures(coords));
    const z = await fetchJson("/api/zone/" + zones[0]);
    setSource("zone", [{ type: "Feature", geometry: { type: "Polygon", coordinates: [z.ring.map((p) => [p.lon, p.lat])] } }]);
    const route = res.trace_name === "upload" ? "maps_fair_route" : state.fixtures.trace_routes[res.trace_name];
    if (route) {
      const r = await fetchJson("/api/route/" + route);
      setSource("route", lineFeatures(r.points.map((p) => [p.lon, p.lat])));
    }
    fitJunction(coords);
    renderVerdict(res);
    document.getElementById("trace-hint").textContent = "Custom trace · " + pts.length + " points";
  } catch (e) {
    alert("Audit failed: " + e.message);
  }
}

function parseTraceJson(text) {
  const data = JSON.parse(text);
  const arr = Array.isArray(data) ? data
    : data.features && data.features[0] && data.features[0].geometry &&
      data.features[0].geometry.type === "LineString"
      ? data.features[0].geometry.coordinates.map((c, i) => ({ lon: c[0], lat: c[1], t: i }))
      : Array.isArray(data.points) ? data.points
      : null;
  if (!arr) throw new Error("expected {points:[...]} or GeoJSON LineString");
  return arr.map((p) => ({ lat: Number(p.lat), lon: Number(p.lon), t: Number(p.t) || 0 }))
    .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
}

function stopPlayback() {
  state.playing = false;
  if (state.timer) { clearInterval(state.timer); state.timer = null; }
  if (map.getLayer("replay-marker")) map.removeLayer("replay-marker");
  if (map.getLayer("replay-arrow")) map.removeLayer("replay-arrow");
  if (map.getSource("replay")) map.removeSource("replay");
}

function play() {
  if (!state.current || !state.current.points || state.current.points.length < 2) return;
  stopPlayback();
  ensureOverlay();
  state.playing = true;

  const pts = state.current.points;
  const coords = pts.map((p) => [p.lon, p.lat]);
  let i = 0;

  if (!map.getSource("replay")) map.addSource("replay", geojsonSource());
  if (!map.getLayer("replay-marker")) {
    map.addLayer({
      id: "replay-marker",
      type: "circle",
      source: "replay",
      paint: {
        "circle-color": "#0f172a",
        "circle-radius": 7,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
      },
    });
    map.addLayer({
      id: "replay-arrow",
      type: "line",
      source: "replay",
      layout: { "line-cap": "round" },
      paint: { "line-color": "#0f172a", "line-width": 3, "line-opacity": 0.55 },
    });
  }
  map.getSource("replay").setData({ type: "FeatureCollection", features: lineFeatures([coords[0]]) });

  state.timer = setInterval(() => {
    i = Math.min(i + 1, pts.length - 1);
    const ahead = Math.min(i + 3, pts.length - 1);
    map.getSource("replay").setData({
      type: "FeatureCollection",
      features: [
        { type: "Feature", geometry: { type: "Point", coordinates: coords[i] } },
        lineFeatures(coords.slice(Math.max(0, i - 12), ahead + 1))[0],
      ],
    });
    if (i >= pts.length - 1) {
      clearInterval(state.timer);
      state.timer = null;
      state.playing = false;
    }
  }, 110);
}

window.addEventListener("DOMContentLoaded", initUi);
document.getElementById("trace-file").addEventListener("change", (e) => {
  const f = e.target.files && e.target.files[0];
  if (f) onUpload(f);
  e.target.value = "";
});
window.audit = audit;
window.review = review;
window.play = play;

map.on("load", () => {
  ensureOverlay();
  document.getElementById("coord-readout").textContent = "22.3228°N 73.2550°E";
});