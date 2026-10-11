"use strict";
/* Env-AI-Ron planner: Digital Twin map. Plain JS + Leaflet, no build step. */
const $ = (s) => document.querySelector(s);
const API = "/api/v1";
const KEYS = ["cooling", "carbon", "pollinator", "equity"];
const KEY_LABEL = { cooling: "Cooling", carbon: "Carbon", pollinator: "Pollinators", equity: "Health equity" };
const PALETTE = ["#1b7f5c", "#c4622d", "#6f5fb3", "#b5368a", "#5f8f1f", "#c79a12", "#8a5a2b", "#2b78b0", "#7a8b99"];

let meta = null, state = { id: null, result: null }, map, layers = {}, siteLayer, clusterLayer, objectUrls = [];
const store = (() => { try { return window.localStorage; } catch (e) { return null; } })();
const getKey = () => (store && store.getItem("envairon_key")) || "dev-planner-key";

function authFetch(url, opts = {}) {
  return fetch(url, { ...opts, headers: { ...(opts.headers || {}), "X-API-Key": $("#apikey").value || getKey() } });
}
function say(msg, err = false) { const s = $("#status"); s.textContent = msg; s.classList.toggle("err", err); }
async function errText(r) {
  try { const j = await r.json(); return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); }
  catch (e) { return `Request failed (${r.status})`; }
}

/* ------------------------------------------------------------ goals panel */
function buildSliders(weights) {
  const box = $("#sliders"); box.innerHTML = "";
  KEYS.forEach((k) => {
    const d = document.createElement("div"); d.className = "slider"; d.dataset.k = k;
    d.innerHTML = `<label for="w-${k}">${KEY_LABEL[k]} <output id="o-${k}"></output></label>
      <input id="w-${k}" type="range" min="0" max="100" step="5">`;
    box.appendChild(d);
    const inp = d.querySelector("input"); inp.value = Math.round(weights[k] * 100);
    inp.addEventListener("input", updateSum);
  });
  updateSum();
}
function currentWeights() {
  const raw = {}; KEYS.forEach((k) => (raw[k] = +$(`#w-${k}`).value));
  const t = KEYS.reduce((a, k) => a + raw[k], 0);
  if (t === 0) return null;
  KEYS.forEach((k) => (raw[k] = raw[k] / t));
  return raw;
}
function updateSum() {
  const w = currentWeights();
  KEYS.forEach((k) => { $(`#o-${k}`).textContent = w ? Math.round(w[k] * 100) + "%" : "0%"; });
  $("#weightsum").textContent = w ? "Shares always add up to 100%." : "Raise at least one goal above zero.";
}

async function init() {
  $("#apikey").value = getKey();
  $("#keyform").addEventListener("submit", (e) => { e.preventDefault(); if (store) store.setItem("envairon_key", $("#apikey").value); say("Key saved."); });
  map = L.map("map", { zoomControl: true, minZoom: 12, maxZoom: 19, zoomSnap: 0.25 }).setView([6.499, 3.359], 16);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors", opacity: 0.55 }).addTo(map);
  try {
    meta = await (await fetch(`${API}/meta`)).json();
  } catch (e) { say("Cannot reach the server.", true); return; }
  const sel = $("#preset");
  Object.keys(meta.presets).forEach((p) => { const o = document.createElement("option"); o.value = p; o.textContent = p.replace(/_/g, " "); sel.appendChild(o); });
  sel.addEventListener("change", () => buildSliders(meta.presets[sel.value]));
  buildSliders(meta.presets.balanced);
  $("#run-demo").addEventListener("click", () => run(true));
  $("#uploadform").addEventListener("submit", (e) => { e.preventDefault(); run(false); });
  $("#year").addEventListener("input", () => setYear(+$("#year").value));
  document.querySelectorAll(".tick").forEach((b) => b.addEventListener("click", () => { $("#year").value = b.dataset.y; setYear(+b.dataset.y); }));
  $("#closedetail").addEventListener("click", closeDetail);
  document.querySelectorAll("[data-export]").forEach((b) => b.addEventListener("click", () => download(b.dataset.export)));
  $("#publish").addEventListener("click", publish);
}

/* ------------------------------------------------------------- run / load */
async function run(demo) {
  const w = currentWeights();
  if (!w) { say("Raise at least one goal above zero.", true); return; }
  const fd = new FormData();
  fd.append("preset", $("#preset").value);
  fd.append("weights", JSON.stringify(w));
  fd.append("budget_sites", $("#budget").value || "180");
  if (demo) fd.append("use_demo", "true");
  else {
    const img = $("#f-image").files[0];
    if (!img) { say("Choose an aerial image first.", true); return; }
    fd.append("image", img);
    if ($("#f-bbox").value.trim()) fd.append("bbox", $("#f-bbox").value.trim());
    [["f-soil", "soil_geojson"], ["f-zone", "zoning_geojson"], ["f-wards", "wards_geojson"], ["f-elev", "elevation_tif"]].forEach(([id, name]) => {
      const f = $("#" + id).files[0]; if (f) fd.append(name, f);
    });
  }
  const btns = document.querySelectorAll("button.primary"); btns.forEach((b) => (b.disabled = true));
  say("Reading the land and searching for the best planting sites. This takes about 20 seconds.");
  try {
    const r = await authFetch(`${API}/analyses`, { method: "POST", body: fd });
    if (!r.ok) { say(await errText(r), true); return; }
    const j = await r.json();
    await load(j.id);
    say("Plan ready. Click a tree marker or a priority area to see why it was chosen.");
  } catch (e) { say("The request failed. Check your connection and try again.", true); }
  finally { btns.forEach((b) => (b.disabled = false)); }
}

async function blobUrl(url) {
  const r = await authFetch(url); if (!r.ok) throw new Error(await errText(r));
  const u = URL.createObjectURL(await r.blob()); objectUrls.push(u); return u;
}

async function load(id) {
  const r = await authFetch(`${API}/analyses/${id}`);
  if (!r.ok) { say(await errText(r), true); return; }
  const res = await r.json();
  state = { id, result: res };
  objectUrls.forEach(URL.revokeObjectURL); objectUrls = [];
  Object.values(layers).forEach((l) => map.removeLayer(l)); layers = {};
  if (siteLayer) map.removeLayer(siteLayer);
  const [w, s, e, n] = res.grid.bbox, bounds = [[s, w], [n, e]];
  map.fitBounds(bounds, { padding: [20, 20] });
  const defs = [
    ["image", "Aerial image", "image.jpg", "#7a6a55", true, 1],
    ["classes", "Land cover", "overlays/classes.png", "#6e6e78", false, 0.8],
    ["voids", "Ecological voids", "overlays/voids.png", "#c4452c", true, 0.6],
    ["heat", "Surface heat today", "overlays/heat.png", "#e08a2c", false, 0.8],
    ["cooling", "Cooling from plan", "overlays/cooling20.png", "#2c7d8b", true, 0.9],
    ["habitat", "Habitat quality", "overlays/habitat20.png", "#5f8f1f", false, 0.8],
  ];
  const names = { cooling: ["cooling5.png", "cooling10.png", "cooling20.png"] };
  const urls = {};
  await Promise.all(defs.map(async ([k, , path]) => { urls[k] = await blobUrl(`${API}/analyses/${id}/${path}`); }));
  state.coolUrls = {};
  await Promise.all([5, 10, 20].map(async (h) => { state.coolUrls[h] = await blobUrl(`${API}/analyses/${id}/overlays/cooling${h}.png`); }));
  state.habUrls = {};
  await Promise.all([20].map(async (h) => { state.habUrls[h] = urls.habitat; }));
  defs.forEach(([k, , , , on, op]) => {
    layers[k] = L.imageOverlay(urls[k], bounds, { opacity: op, interactive: false });
    if (on) layers[k].addTo(map);
  });
  buildLayerList(defs);
  drawSites(); drawClusters(res.clusters);
  $("#empty").hidden = true; $("#timebar").hidden = false; $("#foot").hidden = false; $("#clusters-section").hidden = false;
  $("#datanote").textContent = res.data_note || "";
  $("#year").value = 20; setYear(20);
}

function buildLayerList(defs) {
  const box = $("#layerlist"); box.innerHTML = "";
  defs.forEach(([k, label, , color, on]) => {
    const l = document.createElement("label");
    l.innerHTML = `<input type="checkbox" ${on ? "checked" : ""}><span class="sw" style="background:${color}"></span>${label}`;
    l.querySelector("input").addEventListener("change", (e) => (e.target.checked ? layers[k].addTo(map) : map.removeLayer(layers[k])));
    box.appendChild(l);
  });
  const l = document.createElement("label");
  l.innerHTML = `<input type="checkbox" checked><span class="sw" style="background:#1b7f5c"></span>Planting sites`;
  l.querySelector("input").addEventListener("change", (e) => (e.target.checked ? siteLayer.addTo(map) : map.removeLayer(siteLayer)));
  box.appendChild(l);
}

/* --------------------------------------------------------- sites + time */
function crownRadius(site, year) {
  const h = site.horizons, pts = [[0, 0], [5, h["5"].crown_radius_m], [10, h["10"].crown_radius_m], [20, h["20"].crown_radius_m]];
  for (let i = 1; i < pts.length; i++) {
    if (year <= pts[i][0]) { const [x0, y0] = pts[i - 1], [x1, y1] = pts[i]; return y0 + ((year - x0) / (x1 - x0)) * (y1 - y0); }
  }
  return pts[3][1];
}
function speciesColor(sci) { const i = state.result.summary.species_diversity.n_species && Object.keys(state.result.summary.species_diversity.trees_by_species).indexOf(sci); return PALETTE[(i < 0 ? 0 : i) % PALETTE.length]; }

function drawSites() {
  siteLayer = L.layerGroup().addTo(map);
  state.markers = state.result.sites.map((s) => {
    const m = L.circle([s.lat, s.lon], { radius: 4, color: "#fff", weight: 1.2, fillColor: speciesColor(s.species), fillOpacity: 0.9 });
    m.on("click", () => showSite(s)); m.bindTooltip(`${s.common_name}: ${s.stems} trees`, { sticky: true });
    m.addTo(siteLayer); return m;
  });
}
function drawClusters(cl) {
  const ol = $("#clusters"); ol.innerHTML = "";
  cl.slice(0, 6).forEach((c) => {
    const li = document.createElement("li");
    li.innerHTML = `<button><strong>${c.trees} ${c.dominant_common}</strong><span>${c.area_ha} ha, cools about ${c.mean_cooling_c["20"].toFixed(1)} °C by year 20</span></button>`;
    li.querySelector("button").addEventListener("click", () => { map.flyTo([c.lat, c.lon], 18, { duration: 0.8 }); showCluster(c); });
    ol.appendChild(li);
  });
}

function setYear(y) {
  const res = state.result; if (!res) return;
  $("#yearout").textContent = y === 0 ? "Today" : y;
  state.markers.forEach((m, i) => m.setRadius(Math.max(1.2, crownRadius(res.sites[i], y))));
  // cooling overlay: pick the nearest simulated horizon at or after this year, fade by series ratio
  const ser = res.simulation.series, h = y <= 5 ? 5 : y <= 10 ? 10 : 20;
  layers.cooling.setUrl(state.coolUrls[h]);
  const ratio = ser[h].mean_cooling_planted_c > 0 ? Math.min(1, ser[y].mean_cooling_planted_c / ser[h].mean_cooling_planted_c) : 0;
  layers.cooling.setOpacity(0.9 * ratio);
  const d = ser[y];
  $("#readout").innerHTML = [
    ["Cooling at planted sites", `${d.mean_cooling_planted_c.toFixed(2)} °C`, "cool"],
    ["Cooling across 100 m", `${d.mean_cooling_100m_c.toFixed(2)} °C`, "cool"],
    ["New canopy", `${d.canopy_added_ha.toFixed(1)} ha`, "leaf"],
    ["Carbon stored", `${d.tco2_cumulative.toFixed(0)} tCO₂`, "leaf"],
    ["Habitat quality", `${d.habitat_index_mean.toFixed(1)} / 100`, "leaf"],
  ].map(([t, v, c]) => `<div><dt>${t}</dt><dd class="${c}">${v}</dd></div>`).join("");
}

/* -------------------------------------------------------------- details */
function openDetail(html) {
  $("#detailbody").innerHTML = html; $("#detail").hidden = false; document.querySelector(".shell").classList.add("has-detail");
  setTimeout(() => map.invalidateSize(), 50);
}
function closeDetail() { $("#detail").hidden = true; document.querySelector(".shell").classList.remove("has-detail"); setTimeout(() => map.invalidateSize(), 50); }
const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function showSite(s) {
  const h = s.horizons, rg = h["20"].cooling_range_c;
  openDetail(`<h2>${esc(s.common_name)}</h2><p class="sci">${esc(s.species)}</p>
    <p class="why">${esc(s.rationale)}</p>
    <dl>
      <dt>Trees to plant</dt><dd>${s.stems}</dd>
      <dt>Soil</dt><dd>${esc(s.soil)}${s.flood_prone ? ", floods" : ""}</dd>
      <dt>Land use</dt><dd>${esc(s.zone.replace(/_/g, " "))}</dd>
      ${s.ward ? `<dt>Ward</dt><dd>${esc(s.ward)}</dd>` : ""}
      <dt>Cooling, year 5 / 10 / 20</dt><dd>${h["5"].cooling_c.toFixed(2)} / ${h["10"].cooling_c.toFixed(2)} / ${h["20"].cooling_c.toFixed(2)} °C</dd>
      <dt>Year 20 range</dt><dd>${rg[0].toFixed(2)} to ${rg[1].toFixed(2)} °C</dd>
      <dt>Carbon over 20 years</dt><dd>${s.tco2_20yr.toFixed(2)} tCO₂</dd>
      <dt>Habitat quality, year 20</dt><dd>${h["20"].habitat_index.toFixed(0)} / 100</dd>
      <dt>Need for relief</dt><dd>${Math.round(s.equity_priority * 100)} / 100</dd>
    </dl>
    <h3>Pollinators it feeds</h3><ul>${s.pollinator_taxa.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
    <p class="hint" style="margin-top:12px">Site ${esc(s.site_id)} in area ${esc(s.cluster_id)}. Species traits are provisional until reviewed by local botanists.</p>`);
}
function showCluster(c) {
  const mix = Object.entries(c.species_mix).map(([k, v]) => `<li>${esc(k)}: ${v} trees</li>`).join("");
  openDetail(`<h2>Area ${esc(c.cluster_id)}</h2><p class="sci">${c.n_sites} sites, ${c.area_ha} ha</p>
    <p class="why">${esc(c.roi_statement)}</p>
    <h3 style="margin-top:14px">Species mix</h3><ul>${mix}</ul>
    <h3 style="margin-top:14px">Pollinators supported</h3><ul>${c.pollinator_taxa.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`);
}

/* -------------------------------------------------------------- exports */
async function download(path) {
  if (!state.id) return;
  const r = await authFetch(`${API}/analyses/${state.id}/${path}`);
  if (!r.ok) { say(await errText(r), true); return; }
  const cd = r.headers.get("content-disposition") || "", m = /filename="?([^";]+)"?/.exec(cd);
  const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = m ? m[1] : path.split("?")[0]; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
async function publish() {
  if (!state.id) return;
  const r = await authFetch(`${API}/analyses/${state.id}/publish`, { method: "POST" });
  say(r.ok ? "Shared. Neighbours can now open this plan in the community app at /community/." : await errText(r), !r.ok);
}

init();
